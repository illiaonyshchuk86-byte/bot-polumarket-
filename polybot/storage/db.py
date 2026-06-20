"""Database engine/session setup and snapshot serialization helpers."""

from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from ..domain import BookLevel, OrderBook
from .models import Base, OrderBookSnapshot

# Columns added after the initial schema, with their SQLite type + default.
# create_all() does not alter existing tables, so we add them by hand.
_MARKET_MIGRATIONS: list[tuple[str, str]] = [
    ("category", "TEXT DEFAULT ''"),
    ("event_ticker", "TEXT DEFAULT ''"),
    ("sports_market_type", "TEXT DEFAULT ''"),
    ("rewards_enabled", "BOOLEAN DEFAULT 0"),
    ("rewards_max_spread", "FLOAT"),
    ("rewards_min_size", "FLOAT"),
    ("rewards_daily_rate", "FLOAT DEFAULT 0.0"),
    ("holding_rewards_enabled", "BOOLEAN DEFAULT 0"),
    ("fee_rate", "FLOAT"),
    ("rebate_rate", "FLOAT"),
    ("liquidity_usd", "FLOAT DEFAULT 0.0"),
    ("end_ts", "FLOAT DEFAULT 0.0"),
]


def _migrate(engine: Engine) -> None:
    """Add any missing columns to existing tables (idempotent)."""
    inspector = inspect(engine)
    if "markets" not in inspector.get_table_names():
        return
    existing = {col["name"] for col in inspector.get_columns("markets")}
    with engine.begin() as conn:
        for name, ddl in _MARKET_MIGRATIONS:
            if name not in existing:
                conn.execute(text(f"ALTER TABLE markets ADD COLUMN {name} {ddl}"))


def make_engine(db_path: str) -> Engine:
    """Create a SQLite engine, ensuring the parent directory exists."""
    if db_path != ":memory:":
        Path(db_path).expanduser().parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{db_path}", future=True)
    Base.metadata.create_all(engine)
    _migrate(engine)
    return engine


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


def _levels_to_json(levels: list[BookLevel]) -> str:
    return json.dumps([{"price": lv.price, "size": lv.size} for lv in levels])


def _levels_from_json(raw: str, *, reverse: bool) -> list[BookLevel]:
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return []
    levels = [
        BookLevel(price=float(d["price"]), size=float(d["size"]))
        for d in parsed
        if "price" in d and "size" in d
    ]
    levels.sort(key=lambda x: x.price, reverse=reverse)
    return levels


def book_to_snapshot(book: OrderBook, market_id: str) -> OrderBookSnapshot:
    """Build an ORM snapshot row from an in-memory OrderBook."""
    return OrderBookSnapshot(
        market_id=market_id,
        token_id=book.token_id,
        ts=book.timestamp,
        best_bid=book.best_bid(),
        best_ask=book.best_ask(),
        bids_json=_levels_to_json(book.bids),
        asks_json=_levels_to_json(book.asks),
    )


def snapshot_to_book(snap: OrderBookSnapshot) -> OrderBook:
    """Reconstruct an in-memory OrderBook from a stored snapshot."""
    return OrderBook(
        token_id=snap.token_id,
        bids=_levels_from_json(snap.bids_json, reverse=True),
        asks=_levels_from_json(snap.asks_json, reverse=False),
        timestamp=snap.ts,
    )
