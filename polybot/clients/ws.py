"""(Optional / future) WebSocket market stream.

Polymarket exposes a live market WebSocket at
`wss://ws-subscriptions-clob.polymarket.com/ws/market`. The current foundation
uses REST polling (see `polybot.collector`), which is simpler and sufficient
for data collection and paper-trading. A streaming implementation is intentionally
deferred to a later stage and is NOT implemented here yet.
"""

from __future__ import annotations

WS_MARKET_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"


def not_implemented() -> None:
    raise NotImplementedError(
        "WebSocket streaming is deferred. Use REST polling via polybot.collector."
    )
