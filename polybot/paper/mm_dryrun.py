"""Live MM dry-run: runs the market maker against the REAL live order book in
real time, fully simulated. No orders are ever placed.

This mirrors real operation as closely as the data allows: quotes are decided
from the current book, and fills are realised only by subsequent real market
moves (via the shared MMSession fill model). Rewards are not credited.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Callable

from ..clients.clob import ClobClient
from ..clients.gamma import GammaClient, parse_clob_token_ids, parse_market_meta
from ..collector.collector import _market_volume
from ..config import Config, ProMmConfig
from .mm_session import MMReport, MMSession

logger = logging.getLogger(__name__)


class MMDryRun:
    def __init__(
        self,
        config: Config,
        params: ProMmConfig | None = None,
        *,
        gamma: GammaClient | None = None,
        clob: ClobClient | None = None,
    ) -> None:
        self.config = config
        self.params = params or config.strategy.pro_mm
        self.sim = MMSession(self.params)
        self.gamma = gamma or GammaClient(
            config.api.gamma_base,
            timeout_seconds=config.api.timeout_seconds,
            max_retries=config.api.max_retries,
        )
        self.clob = clob or ClobClient(
            config.api.clob_base,
            timeout_seconds=config.api.timeout_seconds,
            max_retries=config.api.max_retries,
        )
        # token_id -> (market_id, rewards_max_spread); remembered so we can keep
        # managing a position even after its market leaves the volume selection.
        self._token_meta: dict[str, tuple[str, float | None]] = {}

    def _select_markets(self) -> list[dict]:
        markets = self.gamma.list_markets(active=True, closed=False, limit=200)
        eligible = [
            m for m in markets if _market_volume(m) >= self.config.collector.min_volume_usd
        ]
        eligible.sort(key=_market_volume, reverse=True)
        if self.config.collector.prioritize_rewards:
            eligible.sort(key=lambda m: not parse_market_meta(m)["rewards_enabled"])
        return eligible[: self.config.collector.max_markets]

    def _poll_cycle(self) -> None:
        # Tokens to manage this cycle = current volume selection UNION any token
        # where we still hold inventory (so positions are never abandoned).
        selected: list[str] = []
        for market in self._select_markets():
            market_id = str(market.get("id") or market.get("conditionId") or "")
            if not market_id:
                continue
            meta = parse_market_meta(market)
            for token_id in parse_clob_token_ids(market):
                self._token_meta[token_id] = (market_id, meta["rewards_max_spread"])
                selected.append(token_id)

        held = [t for t in self.sim.tokens_with_inventory() if t in self._token_meta]
        to_poll = list(dict.fromkeys(selected + held))  # dedup, keep order

        for token_id in to_poll:
            market_id, reward_spread = self._token_meta[token_id]
            try:
                book = self.clob.get_order_book(token_id)
            except Exception as exc:
                logger.warning("book fetch failed for %s: %s", token_id, exc)
                continue
            self.sim.on_book(token_id, market_id, book, reward_spread, time.time())

    def run(
        self,
        minutes: float,
        *,
        interval: float | None = None,
        stop: threading.Event | None = None,
        on_status: Callable[[MMReport, float], None] | None = None,
    ) -> MMReport:
        stop = stop or threading.Event()
        if interval is None:
            interval = float(self.config.collector.poll_interval_seconds)
        start = time.time()
        deadline = start + minutes * 60.0

        while not stop.is_set() and time.time() < deadline:
            cycle_start = time.time()
            try:
                self._poll_cycle()
            except Exception as exc:  # keep the dry-run alive across hiccups
                logger.error("dry-run cycle failed: %s", exc)
            if on_status is not None:
                on_status(self.sim.report(), time.time() - start)
            elapsed = time.time() - cycle_start
            stop.wait(max(0.0, interval - elapsed))

        return self.sim.report()

    def close(self) -> None:
        self.gamma.close()
        self.clob.close()
