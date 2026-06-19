"""Tests for the storage layer: schema migration and snapshot round-trip."""

from __future__ import annotations

from sqlalchemy import create_engine, inspect, text

from polybot.storage.db import make_engine, make_session_factory
from polybot.storage.models import Market


def test_fresh_db_has_mm_columns(tmp_path):
    engine = make_engine(str(tmp_path / "fresh.db"))
    cols = {c["name"] for c in inspect(engine).get_columns("markets")}
    for expected in ("category", "rewards_enabled", "rewards_max_spread", "liquidity_usd"):
        assert expected in cols


def test_migration_adds_columns_to_old_schema(tmp_path):
    db = str(tmp_path / "old.db")
    # Simulate the pre-MM schema: markets table without the new columns.
    raw = create_engine(f"sqlite:///{db}", future=True)
    with raw.begin() as conn:
        conn.execute(text(
            "CREATE TABLE markets ("
            "market_id TEXT PRIMARY KEY, question TEXT, clob_token_ids TEXT, "
            "outcomes TEXT, volume_usd FLOAT, first_seen_ts FLOAT, last_seen_ts FLOAT)"
        ))
        conn.execute(text("INSERT INTO markets (market_id, question) VALUES ('m1', 'Q?')"))
    raw.dispose()

    # make_engine runs the migration.
    engine = make_engine(db)
    cols = {c["name"] for c in inspect(engine).get_columns("markets")}
    assert "rewards_enabled" in cols
    assert "category" in cols

    # Existing row survives and the ORM can read it with new columns.
    Session = make_session_factory(engine)
    with Session() as s:
        m = s.get(Market, "m1")
        assert m is not None
        assert m.question == "Q?"
        assert m.rewards_enabled in (False, 0)


def test_migration_is_idempotent(tmp_path):
    db = str(tmp_path / "idem.db")
    make_engine(db)
    # Running again must not raise (columns already exist).
    make_engine(db)
