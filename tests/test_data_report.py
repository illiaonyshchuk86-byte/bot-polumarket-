"""Tests for the data report (valid SQL, sane output, handles empty DB)."""

from __future__ import annotations

import json

from polybot.analysis.data_report import build_data_report
from polybot.storage.db import make_engine, make_session_factory
from polybot.storage.models import Market, OrderBookSnapshot


def test_empty_db_message(tmp_path):
    engine = make_engine(str(tmp_path / "empty.db"))
    assert "No snapshots" in build_data_report(engine)


def test_report_sections_and_values(tmp_path):
    engine = make_engine(str(tmp_path / "d.db"))
    Session = make_session_factory(engine)
    with Session() as s:
        s.add(Market(
            market_id="m1", question="Will X win?", clob_token_ids=json.dumps(["yes"]),
            outcomes=json.dumps(["Yes", "No"]), volume_usd=5_000_000.0,
            category="sports", rewards_enabled=True, rewards_max_spread=2.5,
        ))
        # Two snapshots with a moving mid (0.50 -> 0.56) and a 2c spread.
        for ts, bb, ba in [(0.0, 0.49, 0.51), (10.0, 0.55, 0.57)]:
            s.add(OrderBookSnapshot(
                market_id="m1", token_id="yes", ts=ts, best_bid=bb, best_ask=ba,
                bids_json="[]", asks_json="[]",
            ))
        s.commit()

    report = build_data_report(engine)
    assert "DATA REPORT" in report
    assert "spread (cents" in report
    assert "price movement" in report
    assert "sports" in report
    assert "Will X win?" in report
