"""Live paper runner: polls live public books and feeds a SimulationSession.

Read-only + simulated: it fetches real order books but only ever executes
against them in simulation. No real orders are placed.
"""

from __future__ import annotations

import logging
import time

from ..clients.clob import ClobClient
from ..clients.gamma import GammaClient, parse_clob_token_ids, parse_outcomes
from ..config import Config
from ..domain import MarketState
from .session import SessionReport, SimulationSession
from ..strategy.base import Strategy

logger = logging.getLogger(__name__)


def _volume(market: dict) -> float:
    for key in ("volume24hr", "volume24hrClob", "volume", "volumeClob"):
        val = market.get(key)
        if val is not None:
            try:
                return float(val)
            except (TypeError, ValueError):
                continue
    return 0.0


class PaperRunner:
    def __init__(
        self,
        config: Config,
        strategy: Strategy,
        *,
        gamma: GammaClient | None = None,
        clob: ClobClient | None = None,
    ) -> None:
        self.config = config
        self.sim = SimulationSession(config, strategy)
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

    def _select_markets(self) -> list[dict]:
        markets = self.gamma.list_markets(active=True, closed=False, limit=200)
        eligible = [m for m in markets if _volume(m) >= self.config.collector.min_volume_usd]
        eligible.sort(key=_volume, reverse=True)
        return eligible[: self.config.collector.max_markets]

    def _build_state(self, market: dict) -> MarketState | None:
        market_id = str(market.get("id") or market.get("conditionId") or "")
        token_ids = parse_clob_token_ids(market)
        outcome_labels = parse_outcomes(market)
        if not market_id or not token_ids:
            return None

        books = {}
        for tid in token_ids:
            try:
                books[tid] = self.clob.get_order_book(tid)
            except Exception as exc:
                logger.warning("book fetch failed for %s: %s", tid, exc)
        if not books:
            return None

        outcomes = {
            label: tid for label, tid in zip(outcome_labels, token_ids)
        }
        return MarketState(
            market_id=market_id,
            question=str(market.get("question") or market.get("title") or ""),
            books=books,
            outcomes=outcomes,
            timestamp=time.time(),
        )

    def run(self, minutes: float) -> SessionReport:
        deadline = time.time() + minutes * 60.0
        interval = self.config.collector.poll_interval_seconds

        while time.time() < deadline and not self.sim.risk.killed:
            cycle_start = time.time()
            for market in self._select_markets():
                state = self._build_state(market)
                if state is not None:
                    self.sim.process(state)
            elapsed = time.time() - cycle_start
            sleep_for = max(0.0, interval - elapsed)
            if time.time() + sleep_for >= deadline:
                break
            time.sleep(sleep_for)

        return self.sim.report()

    def close(self) -> None:
        self.gamma.close()
        self.clob.close()
