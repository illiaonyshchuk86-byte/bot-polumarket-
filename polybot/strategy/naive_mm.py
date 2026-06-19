"""Demo strategy: naive single-token market maker (EDUCATIONAL ONLY).

Quotes a symmetric bid/ask around the midpoint of the first outcome token with
a fixed half-spread. This is the simplest possible market-making sketch — it
ignores inventory skew, adverse selection, and competition, so it is NOT
expected to be profitable live. It exists to exercise the order/broker/risk
pipeline end-to-end.
"""

from __future__ import annotations

from ..config import NaiveMmConfig
from ..domain import MarketState, Order, Side
from .base import Strategy


class NaiveMarketMaker(Strategy):
    name = "naive_mm"

    def __init__(self, params: NaiveMmConfig | None = None) -> None:
        super().__init__(params or NaiveMmConfig())

    def on_tick(self, state: MarketState) -> list[Order]:
        books = list(state.books.values())
        if not books:
            return []
        book = books[0]
        mid = book.midpoint()
        if mid is None:
            return []

        half_spread = (self.params.half_spread_cents if self.params else 2.0) / 100.0
        size = self.params.order_size if self.params else 20.0

        bid_price = round(max(0.01, mid - half_spread), 3)
        ask_price = round(min(0.99, mid + half_spread), 3)

        return [
            Order(token_id=book.token_id, side=Side.BUY, price=bid_price, size=size,
                  market_id=state.market_id),
            Order(token_id=book.token_id, side=Side.SELL, price=ask_price, size=size,
                  market_id=state.market_id),
        ]
