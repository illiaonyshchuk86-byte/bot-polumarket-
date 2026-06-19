"""Strategy interface.

A strategy receives a MarketState on each tick and returns a list of Orders
(possibly empty). Strategies must be pure with respect to execution — they
propose orders; the broker/risk layer decides what actually happens. This keeps
the same strategy usable in backtest, paper, and (future) live modes.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..domain import MarketState, Order


class Strategy(ABC):
    name: str = "strategy"

    def __init__(self, params: object | None = None) -> None:
        self.params = params

    @abstractmethod
    def on_tick(self, state: MarketState) -> list[Order]:
        """Return orders to submit for this market state (may be empty)."""
        raise NotImplementedError

    # Optional hook for strategies that surface non-trading signals (e.g. the
    # arbitrage scanner emits alerts). Default: no signals.
    def drain_signals(self) -> list[str]:
        return []
