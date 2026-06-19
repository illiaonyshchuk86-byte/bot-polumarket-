"""Pre-trade risk checks and a kill switch.

`RiskManager.check_order` returns (allowed, reason). A strategy's orders are
filtered through this before reaching the (paper) broker. The daily loss cap
and kill switch halt all new trading once tripped.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..config import RiskConfig
from ..domain import Order, Side
from ..paper.portfolio import Portfolio


@dataclass
class RiskDecision:
    allowed: bool
    reason: str = ""


class RiskManager:
    def __init__(self, config: RiskConfig) -> None:
        self.config = config
        self._killed = False

    @property
    def killed(self) -> bool:
        return self._killed

    def kill(self, reason: str = "manual") -> None:
        self._killed = True
        self._kill_reason = reason

    def update_pnl_and_check(self, realized_pnl: float) -> None:
        """Trip the kill switch if the daily realized loss cap is breached."""
        if realized_pnl <= -abs(self.config.daily_loss_cap_usd):
            self.kill(reason="daily_loss_cap")

    def check_order(
        self, order: Order, portfolio: Portfolio, marks: dict[str, float]
    ) -> RiskDecision:
        """Validate a prospective order against configured limits."""
        if self._killed:
            return RiskDecision(False, "kill switch active")

        if order.size <= 0 or order.price < 0:
            return RiskDecision(False, "invalid order size/price")

        # Projected notional for this order.
        order_notional = order.size * order.price

        # Per-market position limit (approximate, using order price as mark).
        current_qty = portfolio.position(order.token_id)
        sign = 1.0 if order.side == Side.BUY else -1.0
        projected_qty = current_qty + sign * order.size
        projected_position_usd = abs(projected_qty) * order.price
        if projected_position_usd > self.config.max_position_usd_per_market + 1e-9:
            return RiskDecision(
                False,
                f"per-market limit exceeded: ${projected_position_usd:.2f} > "
                f"${self.config.max_position_usd_per_market:.2f}",
            )

        # Total gross exposure limit (only buys add fresh exposure here).
        if order.side == Side.BUY:
            gross = order_notional
            for token_id, qty in portfolio.positions.items():
                mark = marks.get(token_id, 0.0)
                gross += abs(qty) * mark
            if gross > self.config.max_total_exposure_usd + 1e-9:
                return RiskDecision(
                    False,
                    f"total exposure limit exceeded: ${gross:.2f} > "
                    f"${self.config.max_total_exposure_usd:.2f}",
                )

        return RiskDecision(True)
