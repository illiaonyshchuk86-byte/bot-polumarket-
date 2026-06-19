"""Market-making backtest: replays stored snapshots through a shared MMSession.

The fill model, adverse selection, and honesty constraints live in
polybot.paper.mm_session (shared with the live dry-run), so backtest and
dry-run produce results from identical logic.
"""

from __future__ import annotations

import json

from sqlalchemy import func, select
from sqlalchemy.engine import Engine

from ..config import Config, ProMmConfig
from ..paper.mm_session import MMReport, MMSession
from ..storage.db import make_engine, make_session_factory, snapshot_to_book
from ..storage.models import Market, OrderBookSnapshot


class MMBacktest:
    def __init__(
        self,
        config: Config,
        params: ProMmConfig | None = None,
        *,
        engine: Engine | None = None,
    ) -> None:
        self.config = config
        self.params = params or config.strategy.pro_mm
        self.engine = engine or make_engine(config.db_path)
        self.Session = make_session_factory(self.engine)

    def _token_reward_spread(self, session) -> dict[str, float | None]:
        """Map each outcome token to its market's rewards_max_spread (cents)."""
        mapping: dict[str, float | None] = {}
        for m in session.scalars(select(Market)).all():
            try:
                token_ids = [str(t) for t in json.loads(m.clob_token_ids)]
            except (json.JSONDecodeError, TypeError):
                continue
            for tid in token_ids:
                mapping[tid] = m.rewards_max_spread
        return mapping

    def run(self) -> MMReport:
        sim = MMSession(self.params)

        with self.Session() as session:
            reward_map = self._token_reward_spread(session)

            # Only replay the recent window, streaming one token at a time, so
            # memory stays bounded as the dataset grows to millions of rows.
            max_ts = session.scalar(select(func.max(OrderBookSnapshot.ts))) or 0.0
            cutoff = max_ts - self.params.backtest_lookback_hours * 3600.0
            token_ids = list(
                session.scalars(
                    select(OrderBookSnapshot.token_id)
                    .where(OrderBookSnapshot.ts >= cutoff)
                    .distinct()
                ).all()
            )

            for token_id in token_ids:
                snaps = session.scalars(
                    select(OrderBookSnapshot)
                    .where(
                        OrderBookSnapshot.token_id == token_id,
                        OrderBookSnapshot.ts >= cutoff,
                    )
                    .order_by(OrderBookSnapshot.ts.asc(), OrderBookSnapshot.id.asc())
                )
                for snap in snaps:
                    sim.on_book(
                        token_id,
                        snap.market_id,
                        snapshot_to_book(snap),
                        reward_map.get(token_id),
                        snap.ts,
                    )

        return sim.report()
