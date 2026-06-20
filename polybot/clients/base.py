"""Shared HTTP plumbing for the read-only API clients.

A thin wrapper around httpx with timeouts and bounded retries with exponential
backoff. All methods here are GET-only — by design, this layer can never place
an order.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# Retried on transient network/server errors.
_RETRY_STATUS = {429, 500, 502, 503, 504}


class ReadOnlyHttpClient:
    """Minimal GET-only JSON HTTP client with retries."""

    def __init__(
        self,
        base_url: str,
        *,
        timeout_seconds: float = 15.0,
        max_retries: int = 3,
        client: httpx.Client | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.max_retries = max_retries
        # Allow dependency injection of an httpx.Client for testing.
        self._client = client or httpx.Client(timeout=timeout_seconds)

    def get_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        """GET `path` and return parsed JSON, retrying transient failures."""
        url = f"{self.base_url}/{path.lstrip('/')}"
        last_exc: Exception | None = None

        for attempt in range(self.max_retries + 1):
            try:
                resp = self._client.get(url, params=params)
                if resp.status_code in _RETRY_STATUS:
                    raise httpx.HTTPStatusError(
                        f"retryable status {resp.status_code}",
                        request=resp.request,
                        response=resp,
                    )
                resp.raise_for_status()
                return resp.json()
            except (httpx.TransportError, httpx.HTTPStatusError) as exc:
                last_exc = exc
                if attempt >= self.max_retries:
                    break
                backoff = 2**attempt
                logger.warning(
                    "GET %s failed (attempt %d/%d): %s — retrying in %ss",
                    url,
                    attempt + 1,
                    self.max_retries + 1,
                    exc,
                    backoff,
                )
                time.sleep(backoff)

        assert last_exc is not None
        raise last_exc

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "ReadOnlyHttpClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
