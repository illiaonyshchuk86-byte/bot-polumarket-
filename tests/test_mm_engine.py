"""End-to-end tests for the market-making backtest engine + fill model."""

from __future__ import annotations

import json

from polybot.backtest.mm_engine import MMBacktest
from polybot.config import Config, ProMmConfig
from polybot.storage.db import make_engine, make_session_factory
from polybot.storage.models import Market, OrderBookSnapshot


def _seed(engine, token: str, series: list[tuple[float, float, float]], reward_spread=None):
    """series = list of (ts, best_bid, best_ask)."""
    Session = make_session_factory(engine)
    with Session() as s:
        s.add(Market(
            market_id="m1", question="Q?",
            clob_token_ids=json.dumps([token]), outcomes=json.dumps(["Yes", "No"]),
            rewards_max_spread=reward_spread,
        ))
        for ts, bb, ba in series:
            s.add(OrderBookSnapshot(
                market_id="m1", token_id=token, ts=ts, best_bid=bb, best_ask=ba,
                bids_json=json.dumps([{"price": bb, "size": 100}]),
                asks_json=json.dumps([{"price": ba, "size": 100}]),
            ))
        s.commit()


def _config(db, **mm_over):
    base = dict(
        base_half_spread_cents=2.0, min_half_spread_cents=1.0, vol_spread_coeff=0.0,
        inventory_skew_cents_per_share=0.05, max_inventory_shares=200.0,
        base_size=20.0, min_size=5.0, vol_window_secs=1000.0, jump_kill_cents=100.0,
        clamp_to_reward_zone=False, starting_cash_usd=1000.0,
    )
    base.update(mm_over)
    return Config(db_path=db, strategy={"pro_mm": ProMmConfig(**base)})


def test_round_trip_fill_shows_adverse_selection(tmp_path):
    db = str(tmp_path / "mm.db")
    engine = make_engine(db)
    # Place at .50 -> bid .48/ask .52. Price dips (bid fills @ .48), then rises
    # (ask fills). Because we bought as it fell, the round trip is ~flat/negative.
    _seed(engine, "yes", [
        (0.0, 0.49, 0.51),   # mid .50 -> quote .48/.52
        (10.0, 0.46, 0.47),  # ask .47 <= .48 -> BUY 20 @ .48
        (20.0, 0.50, 0.51),  # bid .50 >= our ask -> SELL 20
    ])
    report = MMBacktest(_config(db), engine=engine).run()
    assert report.total_fills >= 2
    assert report.total_buys >= 1 and report.total_sells >= 1
    assert report.tokens == 1


def test_jump_kill_stands_aside(tmp_path):
    db = str(tmp_path / "mm2.db")
    engine = make_engine(db)
    # Big swings; with a tight jump_kill the maker should stand aside often.
    series = [(float(i * 10), 0.50 - (i % 2) * 0.05, 0.52 - (i % 2) * 0.05) for i in range(8)]
    _seed(engine, "yes", series)
    report = MMBacktest(_config(db, jump_kill_cents=1.0), engine=engine).run()
    assert report.total_kills > 0


def test_empty_db_runs_cleanly(tmp_path):
    db = str(tmp_path / "empty.db")
    engine = make_engine(db)
    report = MMBacktest(_config(db), engine=engine).run()
    assert report.tokens == 0
    assert report.net_pnl() == 0.0
