"""Polymarket liquidity-reward scoring model (verified against the docs).

Per-order score (quadratic, rewards tightness):
    S(s) = ((v - s) / v)^2 * size      for s <= v, else 0
where v = rewards_max_spread (cents), s = order's distance from the midpoint
(cents). Orders below `min_size` do not qualify.

Two-sided aggregation and the two-sided boost:
    Q_one = bid-side score, Q_two = ask-side score   (single-token simplification:
    the YES/NO complement coupling is ignored)
    mid in [0.10, 0.90]:  Q = max(min(Q_one,Q_two), max(Q_one/c, Q_two/c)), c=3
    extreme mids:         Q = min(Q_one, Q_two)

A maker's share of a market's daily pool = Q_self / (Q_self + Q_competitors),
sampled per minute. We estimate Q_competitors from the visible order-book depth
inside the reward zone — i.e. real resting liquidity, not a guess. This tends to
OVERSTATE competition (we count all book size as qualifying), so reward
estimates are conservative.

Honesty notes: in-game multiplier b is taken as 1; complement coupling ignored;
queue/own-order-in-book effects not modelled.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..domain import OrderBook, Quote

_C = 3.0  # two-sided boost scaling factor (per docs)


@dataclass(frozen=True)
class RewardParams:
    max_spread_cents: float
    min_size: float
    daily_rate_usd: float

    @property
    def active(self) -> bool:
        return self.max_spread_cents > 0 and self.daily_rate_usd > 0


def order_score(size: float, spread_cents: float, max_spread_cents: float, min_size: float) -> float:
    """Quadratic score for a single resting order (0 if it doesn't qualify)."""
    if max_spread_cents <= 0 or size < min_size or spread_cents < 0 or spread_cents > max_spread_cents:
        return 0.0
    frac = (max_spread_cents - spread_cents) / max_spread_cents
    return frac * frac * size


def _q_min(q_one: float, q_two: float, mid: float) -> float:
    if 0.10 <= mid <= 0.90:
        return max(min(q_one, q_two), max(q_one / _C, q_two / _C))
    return min(q_one, q_two)


def quote_score(quote: Quote, mid: float, p: RewardParams) -> float:
    """Two-sided Q for our own quote."""
    q_one = order_score(quote.bid_size, (mid - quote.bid_price) * 100.0,
                        p.max_spread_cents, p.min_size) if quote.has_bid() else 0.0
    q_two = order_score(quote.ask_size, (quote.ask_price - mid) * 100.0,
                        p.max_spread_cents, p.min_size) if quote.has_ask() else 0.0
    return _q_min(q_one, q_two, mid)


def book_score(book: OrderBook, mid: float, p: RewardParams) -> float:
    """Two-sided Q for the resting book (our competition)."""
    q_one = sum(
        order_score(lvl.size, (mid - lvl.price) * 100.0, p.max_spread_cents, p.min_size)
        for lvl in book.bids
    )
    q_two = sum(
        order_score(lvl.size, (lvl.price - mid) * 100.0, p.max_spread_cents, p.min_size)
        for lvl in book.asks
    )
    return _q_min(q_one, q_two, mid)


def reward_for_interval(
    quote: Quote | None, book: OrderBook, mid: float, p: RewardParams, dt_seconds: float
) -> float:
    """Estimated reward ($) earned by `quote` resting for `dt_seconds`.

    share = Q_self / (Q_self + Q_competition); pool accrues at daily_rate per day.
    """
    if quote is None or not p.active or dt_seconds <= 0:
        return 0.0
    q_self = quote_score(quote, mid, p)
    if q_self <= 0:
        return 0.0
    q_comp = book_score(book, mid, p)
    share = q_self / (q_self + q_comp) if (q_self + q_comp) > 0 else 0.0
    per_second = p.daily_rate_usd / 86_400.0
    return share * per_second * dt_seconds
