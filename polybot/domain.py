"""In-memory domain types shared across clients, paper broker, backtest, and
strategies. These are deliberately framework-free (plain dataclasses)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


@dataclass(frozen=True)
class BookLevel:
    """A single price level. `price` is in dollars (0..1 for Polymarket
    outcome tokens); `size` is in shares."""

    price: float
    size: float


@dataclass
class OrderBook:
    """Order book for a single outcome token.

    `bids` are sorted highest-price-first, `asks` lowest-price-first.
    """

    token_id: str
    bids: list[BookLevel] = field(default_factory=list)
    asks: list[BookLevel] = field(default_factory=list)
    timestamp: float = 0.0

    def best_bid(self) -> float | None:
        return self.bids[0].price if self.bids else None

    def best_ask(self) -> float | None:
        return self.asks[0].price if self.asks else None

    def midpoint(self) -> float | None:
        bb, ba = self.best_bid(), self.best_ask()
        if bb is None or ba is None:
            return None
        return (bb + ba) / 2.0


@dataclass
class Order:
    """An order produced by a strategy (paper-only at this stage)."""

    token_id: str
    side: Side
    price: float  # limit price in dollars (0..1)
    size: float  # shares
    market_id: str | None = None


@dataclass
class Fill:
    """Result of (simulated) execution of an order."""

    token_id: str
    side: Side
    filled_size: float
    avg_price: float
    fee: float
    market_id: str | None = None


@dataclass
class MarketState:
    """Snapshot passed to a strategy on each tick.

    For binary markets, `books` is keyed by token_id and typically contains the
    YES and NO outcome tokens.
    """

    market_id: str
    question: str
    books: dict[str, OrderBook] = field(default_factory=dict)
    # Maps a human outcome label ("Yes"/"No") to its token_id when known.
    outcomes: dict[str, str] = field(default_factory=dict)
    timestamp: float = 0.0
