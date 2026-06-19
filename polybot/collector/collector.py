"""Polls Gamma for active markets and CLOB for their order books, persisting
periodic snapshots to SQLite for later backtesting.

Read-only: no orders are ever placed.
"""

from __future__ import annotations

import json
import logging
import threading
import time

from ..clients.clob import ClobClient
from ..clients.gamma import GammaClient, parse_clob_token_ids, parse_outcomes
from ..config import Config
from ..storage.db import book_to_snapshot, make_engine, make_session_factory
from ..storage.models import Market

logger = logging.getLogger(__name__)


def _market_volume(market: dict) -> float:
    for key in ("volume24hr", "volume24hrClob", "volume", "volumeClob"):
        val = market.get(key)
        if val is not None:
            try:
                return float(val)
            except (TypeError, ValueError):
                continue
    return 0.0


class Collector:
    def __init__(
        self,
        config: Config,
        *,
        gamma: GammaClient | None = None,
        clob: ClobClient | None = None,
    ) -> None:
        self.config = config
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
        self.engine = make_engine(config.db_path)
        self.Session = make_session_factory(self.engine)

    def select_markets(self) -> list[dict]:
        """Fetch active markets, filter by volume, and keep the top N."""
        markets = self.gamma.list_markets(active=True, closed=False, limit=200)
        eligible = [
            m for m in markets if _market_volume(m) >= self.config.collector.min_volume_usd
        ]
        eligible.sort(key=_market_volume, reverse=True)
        return eligible[: self.config.collector.max_markets]

    def collect_once(self, stop: "threading.Event | None" = None) -> int:
        """Run a single collection cycle. Returns the number of snapshots saved.

        If a `stop` event is provided and set mid-cycle, the cycle aborts early
        (committing whatever was gathered) so shutdown stays responsive.
        """
        now = time.time()
        markets = self.select_markets()
        snapshots_saved = 0

        with self.Session() as session:
            for m in markets:
                if stop is not None and stop.is_set():
                    break
                market_id = str(m.get("id") or m.get("conditionId") or "")
                if not market_id:
                    continue
                token_ids = parse_clob_token_ids(m)
                outcomes = parse_outcomes(m)

                self._upsert_market(session, market_id, m, token_ids, outcomes, now)

                for token_id in token_ids:
                    if stop is not None and stop.is_set():
                        break
                    try:
                        book = self.clob.get_order_book(token_id)
                    except Exception as exc:  # network/parse — keep cycle alive
                        logger.warning("order book fetch failed for %s: %s", token_id, exc)
                        continue
                    if not book.timestamp:
                        book.timestamp = now
                    self._truncate_depth(book)
                    session.add(book_to_snapshot(book, market_id))
                    snapshots_saved += 1

            session.commit()

        logger.info("collected %d snapshots across %d markets", snapshots_saved, len(markets))
        return snapshots_saved

    def _truncate_depth(self, book) -> None:
        """Cap stored book depth to `collector.max_book_depth` levels per side."""
        depth = self.config.collector.max_book_depth
        if depth and depth > 0:
            book.bids = book.bids[:depth]
            book.asks = book.asks[:depth]

    def _upsert_market(
        self,
        session,
        market_id: str,
        raw: dict,
        token_ids: list[str],
        outcomes: list[str],
        now: float,
    ) -> None:
        existing = session.get(Market, market_id)
        if existing is None:
            session.add(
                Market(
                    market_id=market_id,
                    question=str(raw.get("question") or raw.get("title") or ""),
                    clob_token_ids=json.dumps(token_ids),
                    outcomes=json.dumps(outcomes),
                    volume_usd=_market_volume(raw),
                    first_seen_ts=now,
                    last_seen_ts=now,
                )
            )
        else:
            existing.last_seen_ts = now
            existing.volume_usd = _market_volume(raw)

    def run(self, minutes: float) -> int:
        """Poll on the configured interval for `minutes`. Returns total snapshots."""
        deadline = time.time() + minutes * 60.0
        interval = self.config.collector.poll_interval_seconds
        total = 0
        while time.time() < deadline:
            cycle_start = time.time()
            total += self.collect_once()
            elapsed = time.time() - cycle_start
            sleep_for = max(0.0, interval - elapsed)
            if time.time() + sleep_for >= deadline:
                break
            time.sleep(sleep_for)
        return total

    def run_forever(self, stop: "threading.Event | None" = None) -> int:
        """Collect indefinitely until `stop` is set (or SIGINT/SIGTERM).

        Designed for daemon/VPS use: each cycle is wrapped so a transient
        network or API error is logged and retried on the next interval rather
        than crashing the process. Returns the total snapshots collected.
        """
        stop = stop or threading.Event()
        interval = self.config.collector.poll_interval_seconds
        total = 0
        consecutive_errors = 0

        logger.info(
            "collector daemon started: interval=%ss markets=%s depth=%s db=%s",
            interval,
            self.config.collector.max_markets,
            self.config.collector.max_book_depth,
            self.config.db_path,
        )

        while not stop.is_set():
            cycle_start = time.time()
            try:
                total += self.collect_once(stop)
                consecutive_errors = 0
            except Exception as exc:  # keep the daemon alive across failures
                consecutive_errors += 1
                logger.error(
                    "collection cycle failed (%d in a row): %s",
                    consecutive_errors,
                    exc,
                )
                # Back off (capped) when the API/network is unhappy.
                backoff = min(interval * consecutive_errors, 300)
                stop.wait(backoff)
                continue

            elapsed = time.time() - cycle_start
            stop.wait(max(0.0, interval - elapsed))

        logger.info("collector daemon stopped: %d total snapshots collected", total)
        return total

    def close(self) -> None:
        self.gamma.close()
        self.clob.close()
