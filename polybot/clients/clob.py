"""Read-only client for the CLOB API (order books & prices).

Host: https://clob.polymarket.com

Note: market-data reads (order book, price, midpoint) are generally public.
Source documentation is slightly inconsistent on whether some reads require
wallet auth; this is verified empirically during M1. Only *order placement*
(not implemented here) requires authentication.
"""

from __future__ import annotations

from typing import Any

from ..domain import BookLevel, OrderBook
from .base import ReadOnlyHttpClient


class ClobClient:
    def __init__(
        self,
        base_url: str = "https://clob.polymarket.com",
        *,
        timeout_seconds: float = 15.0,
        max_retries: int = 3,
        http: ReadOnlyHttpClient | None = None,
    ) -> None:
        self._http = http or ReadOnlyHttpClient(
            base_url, timeout_seconds=timeout_seconds, max_retries=max_retries
        )

    def get_order_book(self, token_id: str) -> OrderBook:
        """Fetch the live order book for an outcome token."""
        data = self._http.get_json("/book", params={"token_id": token_id})
        return parse_order_book(token_id, data)

    def get_price(self, token_id: str, side: str = "buy") -> float | None:
        """Best price for a side ('buy' or 'sell')."""
        data = self._http.get_json(
            "/price", params={"token_id": token_id, "side": side}
        )
        price = data.get("price") if isinstance(data, dict) else None
        return float(price) if price is not None else None

    def get_midpoint(self, token_id: str) -> float | None:
        data = self._http.get_json("/midpoint", params={"token_id": token_id})
        mid = data.get("mid") if isinstance(data, dict) else None
        return float(mid) if mid is not None else None

    def close(self) -> None:
        self._http.close()


def _parse_levels(raw_levels: Any, *, reverse: bool) -> list[BookLevel]:
    """Parse a list of {price, size} dicts into sorted BookLevels.

    `reverse=True` for bids (highest price first), False for asks (lowest first).
    """
    levels: list[BookLevel] = []
    for lvl in raw_levels or []:
        try:
            price = float(lvl["price"])
            size = float(lvl["size"])
        except (KeyError, TypeError, ValueError):
            continue
        if size <= 0:
            continue
        levels.append(BookLevel(price=price, size=size))
    levels.sort(key=lambda x: x.price, reverse=reverse)
    return levels


def parse_order_book(token_id: str, data: dict[str, Any]) -> OrderBook:
    """Convert a raw CLOB /book response into an OrderBook."""
    timestamp = 0.0
    if isinstance(data, dict):
        ts = data.get("timestamp")
        try:
            timestamp = float(ts) if ts is not None else 0.0
        except (TypeError, ValueError):
            timestamp = 0.0
        # The CLOB API returns the book timestamp in milliseconds; normalize to
        # seconds so callers never mix units.
        if timestamp > 1e11:
            timestamp /= 1000.0
    bids = _parse_levels(data.get("bids") if isinstance(data, dict) else None, reverse=True)
    asks = _parse_levels(data.get("asks") if isinstance(data, dict) else None, reverse=False)
    return OrderBook(token_id=token_id, bids=bids, asks=asks, timestamp=timestamp)
