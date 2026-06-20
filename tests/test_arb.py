"""Tests for the arbitrage scanner and risk limits."""

from __future__ import annotations

from polybot.config import ArbScannerConfig, RiskConfig
from polybot.domain import BookLevel, MarketState, Order, OrderBook, Side
from polybot.paper.portfolio import Portfolio
from polybot.risk.limits import RiskManager
from polybot.strategy.arb_scanner import ArbScanner


def _binary_state(ask_yes: float, ask_no: float) -> MarketState:
    yes = OrderBook(token_id="yes", bids=[BookLevel(ask_yes - 0.02, 100)],
                    asks=[BookLevel(ask_yes, 100)])
    no = OrderBook(token_id="no", bids=[BookLevel(ask_no - 0.02, 100)],
                   asks=[BookLevel(ask_no, 100)])
    return MarketState(market_id="m1", question="Q?", books={"yes": yes, "no": no})


def test_arb_flags_when_combined_under_one():
    scanner = ArbScanner(ArbScannerConfig(min_edge_cents=1.0))
    scanner.on_tick(_binary_state(0.45, 0.50))  # combined 0.95 -> 5c edge
    signals = scanner.drain_signals()
    assert len(signals) == 1
    assert "ARB" in signals[0]


def test_arb_silent_when_no_edge():
    scanner = ArbScanner(ArbScannerConfig(min_edge_cents=1.0))
    scanner.on_tick(_binary_state(0.50, 0.51))  # combined 1.01 -> negative edge
    assert scanner.drain_signals() == []


def test_arb_emits_no_orders():
    scanner = ArbScanner(ArbScannerConfig(min_edge_cents=1.0))
    orders = scanner.on_tick(_binary_state(0.40, 0.40))
    assert orders == []  # alert-only by design


def test_risk_blocks_oversized_position():
    risk = RiskManager(RiskConfig(max_position_usd_per_market=10.0))
    pf = Portfolio(starting_cash=1000.0)
    order = Order("yes", Side.BUY, price=0.50, size=100)  # $50 notional
    decision = risk.check_order(order, pf, {})
    assert not decision.allowed


def test_risk_kill_switch_on_loss_cap():
    risk = RiskManager(RiskConfig(daily_loss_cap_usd=20.0))
    risk.update_pnl_and_check(-25.0)
    assert risk.killed
    pf = Portfolio(starting_cash=1000.0)
    decision = risk.check_order(Order("yes", Side.BUY, 0.1, 1), pf, {})
    assert not decision.allowed
