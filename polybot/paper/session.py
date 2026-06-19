"""Shared simulation session: wires strategy -> risk -> broker -> portfolio.

Both the backtest engine and the live paper runner feed a stream of MarketState
objects into a SimulationSession, so a strategy behaves identically in either.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..config import Config
from ..domain import MarketState
from ..risk.limits import RiskManager
from ..strategy.base import Strategy
from .broker import PaperBroker
from .portfolio import Portfolio


@dataclass
class SessionReport:
    starting_cash: float
    final_equity: float
    realized_pnl: float
    fees_paid: float
    num_fills: int
    signals: list[str] = field(default_factory=list)
    risk_blocks: int = 0
    killed: bool = False

    def net_pnl(self) -> float:
        return self.final_equity - self.starting_cash


class SimulationSession:
    def __init__(self, config: Config, strategy: Strategy) -> None:
        self.config = config
        self.strategy = strategy
        self.portfolio = Portfolio(starting_cash=config.paper.starting_cash_usd)
        self.broker = PaperBroker(
            taker_fee_bps=config.paper.taker_fee_bps,
            extra_slippage_bps=config.paper.extra_slippage_bps,
        )
        self.risk = RiskManager(config.risk)
        self._marks: dict[str, float] = {}
        self.num_fills = 0
        self.risk_blocks = 0
        self.signals: list[str] = []

    def _update_marks(self, state: MarketState) -> None:
        for token_id, book in state.books.items():
            mid = book.midpoint()
            if mid is not None:
                self._marks[token_id] = mid

    def process(self, state: MarketState) -> None:
        """Run one market tick through the full pipeline."""
        self._update_marks(state)

        orders = self.strategy.on_tick(state)
        for order in orders:
            decision = self.risk.check_order(order, self.portfolio, self._marks)
            if not decision.allowed:
                self.risk_blocks += 1
                continue
            book = state.books.get(order.token_id)
            if book is None:
                continue
            fill = self.broker.execute(order, book)
            if fill.filled_size > 0:
                self.portfolio.apply_fill(fill)
                self.num_fills += 1

        # Collect any non-trading signals (e.g. arbitrage alerts).
        self.signals.extend(self.strategy.drain_signals())

        # Update kill switch on realized losses.
        self.risk.update_pnl_and_check(self.portfolio.realized_pnl)

    def report(self) -> SessionReport:
        return SessionReport(
            starting_cash=self.portfolio.starting_cash,
            final_equity=self.portfolio.mark_to_market(self._marks),
            realized_pnl=self.portfolio.realized_pnl,
            fees_paid=self.portfolio.fees_paid,
            num_fills=self.num_fills,
            signals=self.signals,
            risk_blocks=self.risk_blocks,
            killed=self.risk.killed,
        )
