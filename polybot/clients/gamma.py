"""Read-only client for the Gamma API (market & event metadata).

Host: https://gamma-api.polymarket.com — no authentication required.
"""

from __future__ import annotations

import json
from typing import Any

from .base import ReadOnlyHttpClient


class GammaClient:
    def __init__(
        self,
        base_url: str = "https://gamma-api.polymarket.com",
        *,
        timeout_seconds: float = 15.0,
        max_retries: int = 3,
        http: ReadOnlyHttpClient | None = None,
    ) -> None:
        self._http = http or ReadOnlyHttpClient(
            base_url, timeout_seconds=timeout_seconds, max_retries=max_retries
        )

    def list_markets(
        self,
        *,
        active: bool = True,
        closed: bool = False,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """List markets with common filters. Returns raw market dicts."""
        params = {
            "active": str(active).lower(),
            "closed": str(closed).lower(),
            "limit": limit,
            "offset": offset,
        }
        data = self._http.get_json("/markets", params=params)
        # Gamma may return a bare list or a wrapped object depending on version.
        if isinstance(data, dict) and "data" in data:
            return list(data["data"])
        return list(data)

    def get_market(self, market_id: str) -> dict[str, Any]:
        """Fetch a single market by id."""
        return self._http.get_json(f"/markets/{market_id}")

    def close(self) -> None:
        self._http.close()


def parse_clob_token_ids(market: dict[str, Any]) -> list[str]:
    """Extract CLOB outcome token ids from a Gamma market dict.

    Gamma encodes `clobTokenIds` as a JSON-encoded string (e.g. '["123","456"]')
    in many responses; handle both string and list forms defensively.
    """
    raw = market.get("clobTokenIds")
    if raw is None:
        return []
    if isinstance(raw, list):
        return [str(t) for t in raw]
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            return [str(t) for t in parsed]
        except (json.JSONDecodeError, TypeError):
            return []
    return []


def parse_outcomes(market: dict[str, Any]) -> list[str]:
    """Extract outcome labels (e.g. ["Yes", "No"]) from a Gamma market dict."""
    raw = market.get("outcomes")
    if isinstance(raw, list):
        return [str(o) for o in raw]
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            return [str(o) for o in parsed]
        except (json.JSONDecodeError, TypeError):
            return []
    return []
