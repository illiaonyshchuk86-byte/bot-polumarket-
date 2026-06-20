"""Tracks simulated cash, positions, fees, and PnL."""

from __future__ import annotations

from dataclasses import dataclass, field

from ..domain import Fill, Side


@dataclass
class Portfolio:
    starting_cash: float
    cash: float = field(init=False)
    # token_id -> net shares held (can be negative if short, though Polymarket
    # outcome tokens are typically long-only; we allow it for generality).
    positions: dict[str, float] = field(default_factory=dict)
    # token_id -> volume-weighted average cost of the current position.
    avg_cost: dict[str, float] = field(default_factory=dict)
    realized_pnl: float = 0.0
    fees_paid: float = 0.0

    def __post_init__(self) -> None:
        self.cash = self.starting_cash

    def apply_fill(self, fill: Fill) -> None:
        """Update cash, position, and realized PnL from a simulated fill."""
        if fill.filled_size <= 0:
            return

        self.fees_paid += fill.fee
        self.cash -= fill.fee

        prev_qty = self.positions.get(fill.token_id, 0.0)
        prev_cost = self.avg_cost.get(fill.token_id, 0.0)

        if fill.side == Side.BUY:
            self.cash -= fill.filled_size * fill.avg_price
            new_qty = prev_qty + fill.filled_size
            # Update VWAP cost for the (growing) long position.
            if new_qty != 0:
                self.avg_cost[fill.token_id] = (
                    prev_qty * prev_cost + fill.filled_size * fill.avg_price
                ) / new_qty
            self.positions[fill.token_id] = new_qty
        else:  # SELL
            self.cash += fill.filled_size * fill.avg_price
            # Realize PnL against average cost for the portion sold.
            self.realized_pnl += fill.filled_size * (fill.avg_price - prev_cost)
            new_qty = prev_qty - fill.filled_size
            self.positions[fill.token_id] = new_qty
            if abs(new_qty) < 1e-9:
                self.avg_cost.pop(fill.token_id, None)

    def position(self, token_id: str) -> float:
        return self.positions.get(token_id, 0.0)

    def mark_to_market(self, prices: dict[str, float]) -> float:
        """Total equity = cash + sum(position * mark price)."""
        equity = self.cash
        for token_id, qty in self.positions.items():
            mark = prices.get(token_id)
            if mark is not None:
                equity += qty * mark
        return equity

    def unrealized_pnl(self, prices: dict[str, float]) -> float:
        return self.mark_to_market(prices) - self.starting_cash - self.realized_pnl
