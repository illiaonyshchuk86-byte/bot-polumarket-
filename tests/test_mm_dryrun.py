"""Tests for the shared MMSession and the live dry-run loop (mocked clients)."""

from __future__ import annotations

import threading

from polybot.config import Config, ProMmConfig
from polybot.domain import BookLevel, OrderBook
from polybot.paper.mm_dryrun import MMDryRun
from polybot.paper.mm_session import MMSession


def _book(bid, ask):
    return OrderBook(
        token_id="yes",
        bids=[BookLevel(bid, 100)],
        asks=[BookLevel(ask, 100)],
    )


def test_session_round_trip_fill():
    params = ProMmConfig(
        base_half_spread_cents=2.0, min_half_spread_cents=1.0, vol_spread_coeff=0.0,
        jump_kill_cents=100.0, warmup_ticks=0, clamp_to_reward_zone=False,
        starting_cash_usd=1000.0,
    )
    sim = MMSession(params)
    sim.on_book("yes", "m1", _book(0.49, 0.51), None, ts=0.0)   # quote .48/.52
    sim.on_book("yes", "m1", _book(0.46, 0.47), None, ts=10.0)  # ask .47<=.48 -> BUY
    sim.on_book("yes", "m1", _book(0.50, 0.51), None, ts=20.0)  # bid .50>=ask -> SELL
    r = sim.report()
    assert r.total_buys >= 1 and r.total_sells >= 1


def test_fill_through_ticks_makes_fills_harder():
    base = dict(base_half_spread_cents=2.0, min_half_spread_cents=1.0, vol_spread_coeff=0.0,
                jump_kill_cents=100.0, warmup_ticks=0, clamp_to_reward_zone=False)
    # Touch exactly at the quote: fills with through=0, not with through=1.
    loose = MMSession(ProMmConfig(**base, fill_through_ticks=0.0))
    strict = MMSession(ProMmConfig(**base, fill_through_ticks=1.0))
    for sim in (loose, strict):
        sim.on_book("yes", "m1", _book(0.49, 0.51), None, ts=0.0)   # quote .48/.52
        sim.on_book("yes", "m1", _book(0.47, 0.48), None, ts=10.0)  # ask exactly .48
    assert loose.report().total_buys >= 1
    assert strict.report().total_buys == 0


class _FakeGamma:
    def list_markets(self, **kw):
        return [{
            "id": "m1", "question": "Q?", "volume24hr": 999999,
            "clobTokenIds": "[\"yes\"]", "outcomes": "[\"Yes\",\"No\"]",
            "rewardsMaxSpread": 2.0, "feeType": "sports_fees_v2",
        }]
    def close(self):
        pass


class _FakeClob:
    def __init__(self):
        self.i = 0
        self.seq = [(0.49, 0.51), (0.46, 0.47), (0.50, 0.51)]
    def get_order_book(self, token_id):
        bid, ask = self.seq[min(self.i, len(self.seq) - 1)]
        self.i += 1
        return _book(bid, ask)
    def close(self):
        pass


def test_dryrun_loop_runs_and_fills(monkeypatch):
    cfg = Config(db_path=":memory:")
    cfg.strategy.pro_mm = ProMmConfig(
        base_half_spread_cents=2.0, min_half_spread_cents=1.0, vol_spread_coeff=0.0,
        jump_kill_cents=100.0, warmup_ticks=0, clamp_to_reward_zone=False,
    )
    runner = MMDryRun(cfg, gamma=_FakeGamma(), clob=_FakeClob())

    # Stop almost immediately; we only need a few cycles.
    stop = threading.Event()
    statuses = []

    def on_status(report, elapsed):
        statuses.append(report)
        if len(statuses) >= 3:
            stop.set()

    # interval 0 so cycles run back-to-back.
    report = runner.run(minutes=1.0, interval=0.0, stop=stop, on_status=on_status)
    assert report.tokens == 1
    assert report.steps >= 3
