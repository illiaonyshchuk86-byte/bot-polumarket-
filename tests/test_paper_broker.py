"""Tests for the paper broker fill model and portfolio accounting."""

from __future__ import annotations

from polybot.domain import BookLevel, Order, OrderBook, Side
from polybot.paper.broker import PaperBroker
from polybot.paper.portfolio import Portfolio


def make_book() -> OrderBook:
    return OrderBook(
        token_id="t1",
        bids=[BookLevel(0.40, 100), BookLevel(0.39, 200)],
        asks=[BookLevel(0.42, 80), BookLevel(0.43, 300)],
    )


def test_buy_fills_against_asks_within_limit():
    broker = PaperBroker(taker_fee_bps=0.0, extra_slippage_bps=0.0)
    order = Order(token_id="t1", side=Side.BUY, price=0.43, size=100)
    fill = broker.execute(order, make_book())
    # 80 @ 0.42 + 20 @ 0.43 = 100 shares.
    assert fill.filled_size == 100
    expected_avg = (80 * 0.42 + 20 * 0.43) / 100
    assert abs(fill.avg_price - expected_avg) < 1e-9


def test_buy_stops_at_limit_price():
    broker = PaperBroker()
    order = Order(token_id="t1", side=Side.BUY, price=0.42, size=200)
    fill = broker.execute(order, make_book())
    # Only the 0.42 level qualifies.
    assert fill.filled_size == 80


def test_no_cross_returns_empty_fill():
    broker = PaperBroker()
    order = Order(token_id="t1", side=Side.BUY, price=0.30, size=50)
    fill = broker.execute(order, make_book())
    assert fill.filled_size == 0


def test_sell_fills_against_bids():
    broker = PaperBroker()
    order = Order(token_id="t1", side=Side.SELL, price=0.39, size=150)
    fill = broker.execute(order, make_book())
    assert fill.filled_size == 150
    expected_avg = (100 * 0.40 + 50 * 0.39) / 150
    assert abs(fill.avg_price - expected_avg) < 1e-9


def test_slippage_buffer_raises_buy_cost():
    broker = PaperBroker(extra_slippage_bps=100.0)  # 1%
    order = Order(token_id="t1", side=Side.BUY, price=0.50, size=80)
    fill = broker.execute(order, make_book())
    assert fill.avg_price > 0.42  # paid more than raw best ask due to slippage


def test_portfolio_realizes_pnl_on_sell():
    pf = Portfolio(starting_cash=1000.0)
    broker = PaperBroker()
    buy = broker.execute(Order("t1", Side.BUY, 0.43, 80), make_book())
    pf.apply_fill(buy)
    assert abs(pf.position("t1") - 80) < 1e-9

    sell_book = OrderBook(token_id="t1", bids=[BookLevel(0.50, 80)], asks=[])
    sell = broker.execute(Order("t1", Side.SELL, 0.50, 80), sell_book)
    pf.apply_fill(sell)
    # Bought at 0.42, sold at 0.50 -> 0.08 * 80 = 6.4 realized.
    assert abs(pf.realized_pnl - 6.4) < 1e-6
    assert abs(pf.position("t1")) < 1e-9
