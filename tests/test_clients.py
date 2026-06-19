"""Tests for read-only client parsing against recorded fixtures (no network)."""

from __future__ import annotations

import json
from pathlib import Path

from polybot.clients.clob import parse_order_book
from polybot.clients.gamma import parse_clob_token_ids, parse_outcomes

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def test_parse_clob_token_ids_from_json_string():
    market = _load("gamma_market.json")
    assert parse_clob_token_ids(market) == ["111111", "222222"]


def test_parse_clob_token_ids_from_list():
    assert parse_clob_token_ids({"clobTokenIds": ["a", "b"]}) == ["a", "b"]


def test_parse_clob_token_ids_missing():
    assert parse_clob_token_ids({}) == []


def test_parse_outcomes():
    market = _load("gamma_market.json")
    assert parse_outcomes(market) == ["Yes", "No"]


def test_parse_order_book_sorting_and_top():
    data = _load("clob_book.json")
    book = parse_order_book("111111", data)
    # Bids highest first, asks lowest first.
    assert book.best_bid() == 0.40
    assert book.best_ask() == 0.42
    assert book.midpoint() == (0.40 + 0.42) / 2
    assert book.timestamp == 1718800000.0


def test_parse_order_book_skips_zero_size():
    data = {"bids": [{"price": "0.5", "size": "0"}], "asks": []}
    book = parse_order_book("x", data)
    assert book.bids == []
