"""Simulated order execution against an order book.

The fill model is intentionally conservative but still optimistic relative to
reality: it walks visible book depth, applies a configurable extra-slippage
buffer and a fee, and never assumes more liquidity than the book shows. It does
NOT model market impact, queue position, latency, or adverse selection.
"""

from __future__ import annotations

from ..domain import Fill, Order, OrderBook, Side


class PaperBroker:
    def __init__(self, *, taker_fee_bps: float = 0.0, extra_slippage_bps: float = 0.0) -> None:
        self.taker_fee_bps = taker_fee_bps
        self.extra_slippage_bps = extra_slippage_bps

    def execute(self, order: Order, book: OrderBook) -> Fill:
        """Simulate (partially) filling `order` against `book`.

        BUY fills against asks at prices <= limit; SELL fills against bids at
        prices >= limit. Returns a Fill with the achieved average price (0 size
        if nothing crossed).
        """
        slip = self.extra_slippage_bps / 10_000.0

        if order.side == Side.BUY:
            levels = book.asks
            # An ask level is takeable if its (slippage-adjusted) price <= limit.
            def takeable(price: float) -> bool:
                return price * (1 + slip) <= order.price + 1e-12

            price_adj = lambda p: p * (1 + slip)  # noqa: E731
        else:
            levels = book.bids
            def takeable(price: float) -> bool:
                return price * (1 - slip) >= order.price - 1e-12

            price_adj = lambda p: p * (1 - slip)  # noqa: E731

        remaining = order.size
        notional = 0.0
        filled = 0.0
        for lvl in levels:
            if remaining <= 0:
                break
            if not takeable(lvl.price):
                break
            take = min(remaining, lvl.size)
            notional += take * price_adj(lvl.price)
            filled += take
            remaining -= take

        if filled <= 0:
            return Fill(
                token_id=order.token_id,
                side=order.side,
                filled_size=0.0,
                avg_price=0.0,
                fee=0.0,
                market_id=order.market_id,
            )

        avg_price = notional / filled
        fee = filled * avg_price * (self.taker_fee_bps / 10_000.0)
        return Fill(
            token_id=order.token_id,
            side=order.side,
            filled_size=filled,
            avg_price=avg_price,
            fee=fee,
            market_id=order.market_id,
        )
