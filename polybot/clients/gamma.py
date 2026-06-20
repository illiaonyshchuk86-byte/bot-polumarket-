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


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_market_meta(market: dict[str, Any]) -> dict[str, Any]:
    """Extract market-making-relevant metadata from a Gamma market dict.

    Returns category/grouping hints plus the reward and fee parameters that
    determine whether a market is worth quoting (verified field names against
    the live Gamma API, June 2026).
    """
    sports_type = str(market.get("sportsMarketType") or "")
    fee_type = str(market.get("feeType") or "")
    events = market.get("events")
    ev = events[0] if isinstance(events, list) and events else {}
    event_ticker = str(ev.get("ticker") or ev.get("slug") or "")
    # No clean category field exists; detect sports via sportsMarketType (set on
    # match markets) or feeType (e.g. "sports_fees_v2", set on tournament-winner
    # markets too). Everything else is "other".
    is_sports = bool(sports_type) or "sports" in fee_type.lower()
    category = "sports" if is_sports else "other"

    clob_rewards = market.get("clobRewards") or []
    max_spread = _to_float(market.get("rewardsMaxSpread"))
    min_size = _to_float(market.get("rewardsMinSize"))
    # Sum daily reward pool ($/day) across reward entries.
    daily_rate = 0.0
    for entry in clob_rewards:
        rate = _to_float(entry.get("rewardsDailyRate")) if isinstance(entry, dict) else None
        if rate:
            daily_rate += rate
    rewards_enabled = (daily_rate > 0) or (max_spread is not None and max_spread > 0)

    fee = market.get("feeSchedule") or {}

    return {
        "category": category,
        "event_ticker": event_ticker,
        "sports_market_type": sports_type,
        "rewards_enabled": rewards_enabled,
        "rewards_max_spread": max_spread,
        "rewards_min_size": min_size,
        "rewards_daily_rate": daily_rate,
        "holding_rewards_enabled": bool(market.get("holdingRewardsEnabled")),
        "fee_rate": _to_float(fee.get("rate")),
        "rebate_rate": _to_float(fee.get("rebateRate")),
        "liquidity_usd": _to_float(market.get("liquidityClob") or market.get("liquidity")) or 0.0,
        "end_ts": _parse_iso_ts(market.get("endDate") or market.get("endDateIso")),
    }


def _parse_iso_ts(value: Any) -> float:
    """Parse an ISO-8601 date/datetime into a unix timestamp (0.0 if missing)."""
    if not value or not isinstance(value, str):
        return 0.0
    from datetime import datetime

    s = value.strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(s).timestamp()
    except ValueError:
        # Date-only form (YYYY-MM-DD).
        try:
            return datetime.fromisoformat(s + "T00:00:00+00:00").timestamp()
        except ValueError:
            return 0.0
