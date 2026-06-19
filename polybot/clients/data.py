"""Read-only client for the Data API (positions, activity, price history).

Host: https://data-api.polymarket.com — no authentication required.
"""

from __future__ import annotations

from typing import Any

from .base import ReadOnlyHttpClient


class DataClient:
    def __init__(
        self,
        base_url: str = "https://data-api.polymarket.com",
        *,
        timeout_seconds: float = 15.0,
        max_retries: int = 3,
        http: ReadOnlyHttpClient | None = None,
    ) -> None:
        self._http = http or ReadOnlyHttpClient(
            base_url, timeout_seconds=timeout_seconds, max_retries=max_retries
        )

    def get_positions(self, address: str) -> list[dict[str, Any]]:
        """Current holdings for a wallet address (useful for copy-trading R&D)."""
        data = self._http.get_json("/positions", params={"user": address})
        if isinstance(data, dict) and "data" in data:
            return list(data["data"])
        return list(data) if isinstance(data, list) else []

    def get_activity(self, limit: int = 100) -> list[dict[str, Any]]:
        """Recent global activity feed (trades, market creations)."""
        data = self._http.get_json("/activity", params={"limit": limit})
        if isinstance(data, dict) and "data" in data:
            return list(data["data"])
        return list(data) if isinstance(data, list) else []

    def get_price_history(
        self, token_id: str, *, interval: str = "1h"
    ) -> list[dict[str, Any]]:
        """Historical price points for an outcome token."""
        data = self._http.get_json(
            "/prices-history", params={"market": token_id, "interval": interval}
        )
        if isinstance(data, dict):
            return list(data.get("history", []))
        return list(data) if isinstance(data, list) else []

    def close(self) -> None:
        self._http.close()
