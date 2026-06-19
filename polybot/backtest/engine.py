"""Replays stored snapshots in timestamp order through a SimulationSession.

Each stored snapshot updates the latest known book for its token; the market's
MarketState (built from the latest books of all its tokens) is then ticked into
the strategy. This yields one strategy tick per snapshot.
"""

from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.engine import Engine

from ..config import Config
from ..domain import MarketState
from ..paper.session import SessionReport, SimulationSession
from ..storage.db import make_engine, make_session_factory, snapshot_to_book
from ..storage.models import Market, OrderBookSnapshot
from ..strategy.base import Strategy


class BacktestEngine:
    def __init__(self, config: Config, strategy: Strategy, *, engine: Engine | None = None) -> None:
        self.config = config
        self.strategy = strategy
        self.engine = engine or make_engine(config.db_path)
        self.Session = make_session_factory(self.engine)

    def _load_market_meta(self, session) -> dict[str, Market]:
        return {m.market_id: m for m in session.scalars(select(Market)).all()}

    def run(self) -> SessionReport:
        sim = SimulationSession(self.config, self.strategy)

        with self.Session() as session:
            markets = self._load_market_meta(session)
            # Map each token to its owning market for state assembly.
            token_to_market: dict[str, str] = {}
            for m in markets.values():
                try:
                    for tid in json.loads(m.clob_token_ids):
                        token_to_market[str(tid)] = m.market_id
                except (json.JSONDecodeError, TypeError):
                    continue

            # Latest book per token, accumulated as we replay.
            latest_books: dict[str, object] = {}

            snapshots = session.scalars(
                select(OrderBookSnapshot).order_by(OrderBookSnapshot.ts.asc(), OrderBookSnapshot.id.asc())
            )
            for snap in snapshots:
                if sim.risk.killed:
                    break
                book = snapshot_to_book(snap)
                latest_books[snap.token_id] = book

                market_id = token_to_market.get(snap.token_id, snap.market_id)
                meta = markets.get(market_id)
                # Gather current books for all tokens of this market.
                token_ids = []
                if meta is not None:
                    try:
                        token_ids = [str(t) for t in json.loads(meta.clob_token_ids)]
                    except (json.JSONDecodeError, TypeError):
                        token_ids = [snap.token_id]
                else:
                    token_ids = [snap.token_id]

                books = {
                    tid: latest_books[tid] for tid in token_ids if tid in latest_books
                }
                if not books:
                    continue

                state = MarketState(
                    market_id=market_id,
                    question=meta.question if meta else "",
                    books=books,  # type: ignore[arg-type]
                    timestamp=snap.ts,
                )
                sim.process(state)

        return sim.report()
