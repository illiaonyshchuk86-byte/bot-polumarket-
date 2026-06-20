"""Tests for the multi-factor reward screener verdicts."""

from __future__ import annotations

import json
import time

from polybot.analysis.reward_screener import score_markets
from polybot.config import ScreenerConfig
from polybot.storage.db import make_engine, make_session_factory
from polybot.storage.models import Market, OrderBookSnapshot


def _seed(engine, market_id, token, *, pool, comp_size, end_ts, bb=0.49, ba=0.51):
    Session = make_session_factory(engine)
    with Session() as s:
        s.add(Market(
            market_id=market_id, question=f"Market {market_id}",
            clob_token_ids=json.dumps([token]), outcomes=json.dumps(["Yes", "No"]),
            category="other", rewards_enabled=pool > 0, rewards_max_spread=2.0,
            rewards_min_size=100.0, rewards_daily_rate=pool, liquidity_usd=50000.0,
            end_ts=end_ts,
        ))
        s.add(OrderBookSnapshot(
            market_id=market_id, token_id=token, ts=1000.0, best_bid=bb, best_ask=ba,
            bids_json=json.dumps([{"price": bb, "size": comp_size}]),
            asks_json=json.dumps([{"price": ba, "size": comp_size}]),
        ))
        s.commit()


def _by_id(scores, mid):
    return next(s for s in scores if s.market_id == mid)


def test_verdicts(tmp_path):
    engine = make_engine(str(tmp_path / "s.db"))
    now = time.time()
    _seed(engine, "A", "ta", pool=1000.0, comp_size=100, end_ts=now + 10 * 86400)       # low competition
    _seed(engine, "B", "tb", pool=1000.0, comp_size=5_000_000, end_ts=now + 10 * 86400)  # huge competition
    _seed(engine, "C", "tc", pool=0.0, comp_size=100, end_ts=now + 10 * 86400)           # no reward
    _seed(engine, "D", "td", pool=1000.0, comp_size=100, end_ts=now + 0.5 * 86400)       # resolves soon

    scores = score_markets(engine, ScreenerConfig(capital_per_market_usd=1000.0))

    assert _by_id(scores, "A").verdict == "ATTRACTIVE"
    assert _by_id(scores, "B").verdict == "LOW-YIELD"
    assert _by_id(scores, "C").verdict == "NO-REWARD"
    assert _by_id(scores, "D").verdict == "RESOLVES-SOON"

    # Low-competition market gets a far bigger share than the crowded one.
    assert _by_id(scores, "A").our_share_pct > _by_id(scores, "B").our_share_pct


def test_underfunded(tmp_path):
    engine = make_engine(str(tmp_path / "u.db"))
    _seed(engine, "A", "ta", pool=1000.0, comp_size=100, end_ts=time.time() + 10 * 86400)
    # $10 at mid 0.50 -> 20 shares < min_size 100 -> cannot qualify.
    scores = score_markets(engine, ScreenerConfig(capital_per_market_usd=10.0))
    assert _by_id(scores, "A").verdict == "UNDERFUNDED"
