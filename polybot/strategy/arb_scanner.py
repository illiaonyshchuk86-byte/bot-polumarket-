"""Demo strategy: intra-market YES/NO arbitrage scanner (ALERT ONLY).

For a binary market, the YES and NO outcome tokens resolve to a guaranteed $1
combined. If you can BUY both sides for less than $1 total (best_ask_yes +
best_ask_no < 1.00), that gap is a theoretical arbitrage edge.

This strategy only *flags* such gaps as signals — it intentionally returns no
orders. Real capture requires near-simultaneous fills, fees, and accounting for
the gap usually vanishing in well under a second; treat flagged edges as
research leads, not free money.
"""

from __future__ import annotations

from ..config import ArbScannerConfig
from ..domain import MarketState, Order
from .base import Strategy


class ArbScanner(Strategy):
    name = "arb_scanner"

    def __init__(self, params: ArbScannerConfig | None = None) -> None:
        super().__init__(params or ArbScannerConfig())
        self._signals: list[str] = []

    def on_tick(self, state: MarketState) -> list[Order]:
        books = list(state.books.values())
        if len(books) < 2:
            return []

        # Use the two most-liquid outcome books (binary market assumption).
        yes_book, no_book = books[0], books[1]
        ask_yes = yes_book.best_ask()
        ask_no = no_book.best_ask()
        if ask_yes is None or ask_no is None:
            return []

        combined = ask_yes + ask_no
        edge_cents = (1.0 - combined) * 100.0
        min_edge = self.params.min_edge_cents if self.params else 1.0
        if edge_cents >= min_edge:
            self._signals.append(
                f"[ARB] {state.market_id} '{state.question[:48]}': "
                f"ask_yes={ask_yes:.3f} + ask_no={ask_no:.3f} = {combined:.3f} "
                f"(edge {edge_cents:.2f}¢)"
            )
        return []

    def drain_signals(self) -> list[str]:
        out = self._signals
        self._signals = []
        return out
