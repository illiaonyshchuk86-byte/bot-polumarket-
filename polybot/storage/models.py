"""SQLAlchemy ORM models for collected data.

We store market metadata plus periodic order-book snapshots. Snapshots persist
the full top-of-book levels as JSON so the backtest engine can replay them.
"""

from __future__ import annotations

from sqlalchemy import Float, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Market(Base):
    __tablename__ = "markets"

    market_id: Mapped[str] = mapped_column(String, primary_key=True)
    question: Mapped[str] = mapped_column(Text, default="")
    # JSON-encoded list of CLOB token ids and outcome labels.
    clob_token_ids: Mapped[str] = mapped_column(Text, default="[]")
    outcomes: Mapped[str] = mapped_column(Text, default="[]")
    volume_usd: Mapped[float] = mapped_column(Float, default=0.0)
    first_seen_ts: Mapped[float] = mapped_column(Float, default=0.0)
    last_seen_ts: Mapped[float] = mapped_column(Float, default=0.0)


class OrderBookSnapshot(Base):
    __tablename__ = "orderbook_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    market_id: Mapped[str] = mapped_column(String, index=True)
    token_id: Mapped[str] = mapped_column(String, index=True)
    ts: Mapped[float] = mapped_column(Float, index=True)
    best_bid: Mapped[float | None] = mapped_column(Float, nullable=True)
    best_ask: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Full ladders as JSON: [{"price": .., "size": ..}, ...]
    bids_json: Mapped[str] = mapped_column(Text, default="[]")
    asks_json: Mapped[str] = mapped_column(Text, default="[]")
