"""End-to-end backtest test on a small temporary SQLite database."""

from __future__ import annotations

import json

from polybot.backtest.engine import BacktestEngine
from polybot.config import Config
from polybot.storage.db import make_engine, make_session_factory
from polybot.storage.models import Market, OrderBookSnapshot
from polybot.strategy.arb_scanner import ArbScanner
from polybot.strategy.naive_mm import NaiveMarketMaker


def _seed(engine):
    Session = make_session_factory(engine)
    with Session() as s:
        s.add(
            Market(
                market_id="m1",
                question="Will it rain?",
                clob_token_ids=json.dumps(["yes", "no"]),
                outcomes=json.dumps(["Yes", "No"]),
                volume_usd=10000.0,
                first_seen_ts=1.0,
                last_seen_ts=2.0,
            )
        )
        # YES book (combined with NO will be 0.95 -> arbitrage edge).
        s.add(OrderBookSnapshot(
            market_id="m1", token_id="yes", ts=1.0, best_bid=0.43, best_ask=0.45,
            bids_json=json.dumps([{"price": 0.43, "size": 100}]),
            asks_json=json.dumps([{"price": 0.45, "size": 100}]),
        ))
        s.add(OrderBookSnapshot(
            market_id="m1", token_id="no", ts=1.1, best_bid=0.48, best_ask=0.50,
            bids_json=json.dumps([{"price": 0.48, "size": 100}]),
            asks_json=json.dumps([{"price": 0.50, "size": 100}]),
        ))
        s.commit()


def test_backtest_arb_scanner_finds_edge(tmp_path):
    db = str(tmp_path / "bt.db")
    engine = make_engine(db)
    _seed(engine)

    config = Config(db_path=db)
    report = BacktestEngine(config, ArbScanner(), engine=engine).run()

    assert any("ARB" in s for s in report.signals)
    assert report.num_fills == 0  # scanner places no orders


def test_backtest_naive_mm_runs_pipeline(tmp_path):
    db = str(tmp_path / "bt2.db")
    engine = make_engine(db)
    _seed(engine)

    config = Config(db_path=db)
    report = BacktestEngine(config, NaiveMarketMaker(), engine=engine).run()

    # Pipeline runs to completion and produces a coherent report.
    assert report.starting_cash == config.paper.starting_cash_usd
    assert report.final_equity > 0
    assert report.num_fills >= 0
