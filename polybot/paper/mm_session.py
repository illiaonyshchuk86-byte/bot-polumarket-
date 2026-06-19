"""Shared market-making session: the SINGLE source of truth for the dry-run.

Both the historical backtest and the live dry-run feed order books into an
MMSession, so the simulated behaviour and PnL are computed by identical code.

Fill model (deliberately conservative — no rosy numbers):
  * A resting bid at price p fills only when the next observed best ask trades
    down to <= p - fill_through_ticks*tick (the market moved THROUGH our quote).
  * A resting ask at price p fills only when the next best bid >= p + ...
Because fills happen only on a move toward our quote, adverse selection is
inherent: we buy as price falls and sell as it rises, marked to the new mid.

Honesty constraints:
  * Maker fee is configurable and defaults to 0 (Polymarket makers pay none).
  * Liquidity / maker / holding REWARDS are never credited here. Any profit is
    therefore a floor; rewards would only add to it.
  * No queue position, no partial fills, no sub-interval microstructure.
"""

from __future__ import annotations

import statistics
from collections import deque
from dataclasses import dataclass, field

from ..config import ProMmConfig
from ..domain import OrderBook
from ..strategy.pro_mm import MMQuoteInput, ProMarketMaker

TICK = 0.01


@dataclass
class TokenResult:
    token_id: str
    market_id: str
    realized_cash: float
    inventory: float
    last_mid: float
    fills: int
    buys: int
    sells: int
    kills: int
    max_abs_inventory: float
    steps: int

    def equity(self) -> float:
        return self.realized_cash + self.inventory * self.last_mid


@dataclass
class _TokenState:
    token_id: str
    market_id: str
    reward_spread: float | None = None
    cash: float = 0.0
    inventory: float = 0.0
    resting: object = None  # Quote | None
    mids: deque = field(default_factory=deque)
    fills: int = 0
    buys: int = 0
    sells: int = 0
    kills: int = 0
    max_abs_inventory: float = 0.0
    last_mid: float = 0.0
    steps: int = 0
    equity_changes: list[float] = field(default_factory=list)
    _prev_equity: float = 0.0


@dataclass
class MMReport:
    starting_cash: float
    final_equity: float
    total_fills: int
    total_buys: int
    total_sells: int
    total_kills: int
    max_abs_inventory: float
    tokens: int
    steps: int
    pnl_per_step_mean: float
    pnl_per_step_std: float
    top_tokens: list[TokenResult] = field(default_factory=list)

    def net_pnl(self) -> float:
        return self.final_equity - self.starting_cash

    def return_pct(self) -> float:
        return 100.0 * self.net_pnl() / self.starting_cash if self.starting_cash else 0.0

    def risk_ratio(self) -> float:
        """Rough mean/std of per-step PnL (NOT an annualized Sharpe)."""
        return self.pnl_per_step_mean / self.pnl_per_step_std if self.pnl_per_step_std else 0.0


class MMSession:
    def __init__(self, params: ProMmConfig) -> None:
        self.params = params
        self.maker = ProMarketMaker(params)
        self.states: dict[str, _TokenState] = {}

    def on_book(
        self, token_id: str, market_id: str, book: OrderBook, reward_spread: float | None, ts: float
    ) -> None:
        """Process one order-book observation for a token."""
        bb, ba = book.best_bid(), book.best_ask()
        st = self.states.get(token_id)
        if st is None:
            st = _TokenState(token_id=token_id, market_id=market_id, reward_spread=reward_spread)
            self.states[token_id] = st

        if bb is None or ba is None:
            st.resting = None  # cannot quote a one-sided book
            return

        mid = (bb + ba) / 2.0
        st.last_mid = mid
        st.steps += 1
        through = self.params.fill_through_ticks * TICK

        # 1) Fill the previously resting quote against the move to this book.
        q = st.resting
        if q is not None:
            if q.has_bid() and ba <= q.bid_price - through + 1e-12:
                st.inventory += q.bid_size
                st.cash -= q.bid_size * q.bid_price * (1 + self.params.maker_fee_bps / 10_000.0)
                st.fills += 1
                st.buys += 1
            if q.has_ask() and bb >= q.ask_price + through - 1e-12:
                st.inventory -= q.ask_size
                st.cash += q.ask_size * q.ask_price * (1 - self.params.maker_fee_bps / 10_000.0)
                st.fills += 1
                st.sells += 1

        # 2) Volatility / jump estimates over the rolling window.
        st.mids.append((ts, mid))
        while st.mids and ts - st.mids[0][0] > self.params.vol_window_secs:
            st.mids.popleft()
        window = [m for _, m in st.mids]
        sigma_cents = statistics.pstdev(window) * 100.0 if len(window) >= 2 else 0.0
        jump_cents = (max(window) - min(window)) * 100.0 if window else 0.0

        # 3) Decide the new quote (stable core logic). Stand aside during warmup
        # so we never quote before volatility can be estimated.
        new_quote = None
        if len(window) >= self.params.warmup_ticks:
            new_quote = self.maker.quote(
                MMQuoteInput(
                    mid=mid,
                    sigma_cents=sigma_cents,
                    jump_cents=jump_cents,
                    inventory=st.inventory,
                    rewards_max_spread_cents=st.reward_spread,
                )
            )
            if new_quote is None:
                st.kills += 1  # guard-driven stand-aside (not warmup)
        st.resting = new_quote

        # 4) Metrics.
        st.max_abs_inventory = max(st.max_abs_inventory, abs(st.inventory))
        equity = st.cash + st.inventory * mid
        st.equity_changes.append(equity - st._prev_equity)
        st._prev_equity = equity

    def report(self) -> MMReport:
        results = [
            TokenResult(
                token_id=st.token_id,
                market_id=st.market_id,
                realized_cash=st.cash,
                inventory=st.inventory,
                last_mid=st.last_mid,
                fills=st.fills,
                buys=st.buys,
                sells=st.sells,
                kills=st.kills,
                max_abs_inventory=st.max_abs_inventory,
                steps=st.steps,
            )
            for st in self.states.values()
        ]
        all_changes: list[float] = []
        for st in self.states.values():
            all_changes.extend(st.equity_changes)

        results.sort(key=lambda r: r.equity(), reverse=True)
        net = sum(r.equity() for r in results)
        return MMReport(
            starting_cash=self.params.starting_cash_usd,
            final_equity=self.params.starting_cash_usd + net,
            total_fills=sum(r.fills for r in results),
            total_buys=sum(r.buys for r in results),
            total_sells=sum(r.sells for r in results),
            total_kills=sum(r.kills for r in results),
            max_abs_inventory=max((r.max_abs_inventory for r in results), default=0.0),
            tokens=len(results),
            steps=sum(r.steps for r in results),
            pnl_per_step_mean=statistics.fmean(all_changes) if all_changes else 0.0,
            pnl_per_step_std=statistics.pstdev(all_changes) if len(all_changes) >= 2 else 0.0,
            top_tokens=results[:5],
        )
