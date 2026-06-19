"""Pluggable strategies. The same Strategy works in backtest and paper runs."""

from .base import Strategy
from .arb_scanner import ArbScanner
from .naive_mm import NaiveMarketMaker

# Registry used by the CLI's --strategy flag.
REGISTRY: dict[str, type[Strategy]] = {
    "arb_scanner": ArbScanner,
    "naive_mm": NaiveMarketMaker,
}

__all__ = ["Strategy", "ArbScanner", "NaiveMarketMaker", "REGISTRY"]
