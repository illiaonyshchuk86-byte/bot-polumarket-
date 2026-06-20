"""Tests for the liquidity-reward scoring model."""

from __future__ import annotations

from polybot.domain import BookLevel, OrderBook, Quote
from polybot.paper.rewards import (
    RewardParams,
    book_score,
    order_score,
    quote_score,
    reward_for_interval,
)


def test_order_score_quadratic_decay():
    # At the midpoint (s=0): full size. At the edge (s=v): zero.
    assert order_score(200, 0.0, 2.0, 100) == 200.0
    assert order_score(200, 1.0, 2.0, 100) == 50.0   # ((2-1)/2)^2 * 200
    assert order_score(200, 2.0, 2.0, 100) == 0.0
    assert order_score(200, 3.0, 2.0, 100) == 0.0     # beyond max spread


def test_order_score_min_size_gate():
    assert order_score(50, 0.0, 2.0, 100) == 0.0      # below min size -> no reward
    assert order_score(100, 0.0, 2.0, 100) == 100.0


def test_quote_score_two_sided():
    q = Quote(bid_price=0.49, bid_size=200, ask_price=0.51, ask_size=200)
    s = quote_score(q, mid=0.50, p=RewardParams(2.0, 100, 1000))
    # each side: ((2-1)/2)^2 * 200 = 50; q_min at mid 0.5 = 50
    assert abs(s - 50.0) < 1e-9


def test_reward_share_and_payout():
    p = RewardParams(max_spread_cents=2.0, min_size=100, daily_rate_usd=8640.0)
    q = Quote(0.49, 200, 0.51, 200)
    empty = OrderBook(token_id="t")  # no competition -> we get 100% of the pool
    r = reward_for_interval(q, empty, mid=0.50, p=p, dt_seconds=10.0)
    # share 1.0 * (8640/86400 per sec) * 10s = 1.0
    assert abs(r - 1.0) < 1e-9


def test_reward_share_split_with_competition():
    p = RewardParams(2.0, 100, 8640.0)
    q = Quote(0.49, 200, 0.51, 200)              # our score 50
    book = OrderBook(                             # competitor with equal score
        token_id="t",
        bids=[BookLevel(0.49, 200)],
        asks=[BookLevel(0.51, 200)],
    )
    r = reward_for_interval(q, book, mid=0.50, p=p, dt_seconds=10.0)
    assert abs(r - 0.5) < 1e-9                     # 50/(50+50) * 1.0


def test_no_reward_when_below_min_size():
    p = RewardParams(2.0, 100, 8640.0)
    q = Quote(0.49, 20, 0.51, 20)                 # size 20 < min 100
    r = reward_for_interval(q, OrderBook(token_id="t"), mid=0.50, p=p, dt_seconds=10.0)
    assert r == 0.0


def test_no_reward_when_inactive():
    p = RewardParams(0.0, 0, 0.0)                 # no program
    q = Quote(0.49, 200, 0.51, 200)
    assert reward_for_interval(q, OrderBook(token_id="t"), 0.50, p, 10.0) == 0.0
