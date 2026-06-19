"""Market-making backtest with a snapshot-based maker-fill model.

Maker fills are simulated honestly and conservatively: a resting bid at price
p only fills when the market's best ask later drops to <= p (price came down
THROUGH our quote), and a resting ask fills when the best bid rises to >= p.
Because fills only happen on a move toward our quote, **adverse selection is
built in** — we buy as the price falls and sell as it rises, then mark to the
new midpoint. There is no queue position, partial-fill, or sub-10s microstructure
modelling, so treat results as an optimistic-but-honest approximation.

Rewards are intentionally NOT credited here: if a configuration is profitable
without rewards, the liquidity/maker/holding rewards are pure upside.
"""

from __future__ import annotations

import json
import statistics
from collections import deque
from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.engine import Engine

from ..config import Config, ProMmConfig
from ..storage.db import make_engine, make_session_factory, snapshot_to_book
from ..storage.models import Market, OrderBookSnapshot
from ..strategy.pro_mm import MMQuoteInput, ProMarketMaker


@dataclass
class TokenResult:
    token_id: str
    market_id: str
    realized_cash: float          # cash flow from fills (negative = net bought)
    inventory: float              # leftover position (shares)
    last_mid: float
    fills: int
    buys: int
    sells: int
    kills: int                    # ticks where we stood aside (vol guard / caps)
    max_abs_inventory: float
    steps: int

    def equity(self) -> float:
        return self.realized_cash + self.inventory * self.last_mid


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

    def risk_ratio(self) -> float:
        """Rough mean/std of per-step PnL (NOT an annualized Sharpe)."""
        return self.pnl_per_step_mean / self.pnl_per_step_std if self.pnl_per_step_std else 0.0


class MMBacktest:
    def __init__(
        self,
        config: Config,
        params: ProMmConfig | None = None,
        *,
        engine: Engine | None = None,
    ) -> None:
        self.config = config
        self.params = params or config.strategy.pro_mm
        self.maker = ProMarketMaker(self.params)
        self.engine = engine or make_engine(config.db_path)
        self.Session = make_session_factory(self.engine)

    def _token_reward_spread(self, session) -> dict[str, float | None]:
        """Map each outcome token to its market's rewards_max_spread (cents)."""
        mapping: dict[str, float | None] = {}
        for m in session.scalars(select(Market)).all():
            try:
                token_ids = [str(t) for t in json.loads(m.clob_token_ids)]
            except (json.JSONDecodeError, TypeError):
                continue
            for tid in token_ids:
                mapping[tid] = m.rewards_max_spread
        return mapping

    def _run_token(
        self, token_id: str, market_id: str, snaps: list[OrderBookSnapshot], reward_spread
    ) -> tuple[TokenResult, list[float]]:
        p = self.params
        cash = 0.0
        inventory = 0.0
        resting = None
        mids: deque[tuple[float, float]] = deque()
        fills = buys = sells = kills = 0
        max_abs_inv = 0.0
        last_mid = 0.0
        equity_changes: list[float] = []
        prev_equity = 0.0

        for snap in snaps:
            book = snapshot_to_book(snap)
            bb, ba = book.best_bid(), book.best_ask()
            if bb is None or ba is None:
                resting = None  # can't quote a one-sided book
                continue
            mid = (bb + ba) / 2.0
            last_mid = mid

            # 1) Fill the PREVIOUS resting quote against the move to this snapshot.
            if resting is not None:
                if resting.has_bid() and ba <= resting.bid_price + 1e-9:
                    inventory += resting.bid_size
                    cash -= resting.bid_size * resting.bid_price
                    fills += 1
                    buys += 1
                if resting.has_ask() and bb >= resting.ask_price - 1e-9:
                    inventory -= resting.ask_size
                    cash += resting.ask_size * resting.ask_price
                    fills += 1
                    sells += 1

            # 2) Volatility / jump estimates over the rolling window.
            mids.append((snap.ts, mid))
            while mids and snap.ts - mids[0][0] > p.vol_window_secs:
                mids.popleft()
            window = [m for _, m in mids]
            sigma_cents = statistics.pstdev(window) * 100.0 if len(window) >= 2 else 0.0
            jump_cents = (max(window) - min(window)) * 100.0 if window else 0.0

            # 3) Decide the new quote (stable core logic).
            quote = self.maker.quote(
                MMQuoteInput(
                    mid=mid,
                    sigma_cents=sigma_cents,
                    jump_cents=jump_cents,
                    inventory=inventory,
                    rewards_max_spread_cents=reward_spread,
                )
            )
            if quote is None:
                kills += 1
            resting = quote

            # 4) Metrics.
            max_abs_inv = max(max_abs_inv, abs(inventory))
            equity = cash + inventory * mid
            equity_changes.append(equity - prev_equity)
            prev_equity = equity

        result = TokenResult(
            token_id=token_id,
            market_id=market_id,
            realized_cash=cash,
            inventory=inventory,
            last_mid=last_mid,
            fills=fills,
            buys=buys,
            sells=sells,
            kills=kills,
            max_abs_inventory=max_abs_inv,
            steps=len(snaps),
        )
        return result, equity_changes

    def run(self) -> MMReport:
        results: list[TokenResult] = []
        all_changes: list[float] = []

        with self.Session() as session:
            reward_map = self._token_reward_spread(session)

            # Only backtest the recent window, and stream one token at a time, so
            # memory stays bounded as the dataset grows to millions of rows.
            max_ts = session.scalar(select(func.max(OrderBookSnapshot.ts))) or 0.0
            cutoff = max_ts - self.params.backtest_lookback_hours * 3600.0
            token_ids = list(
                session.scalars(
                    select(OrderBookSnapshot.token_id)
                    .where(OrderBookSnapshot.ts >= cutoff)
                    .distinct()
                ).all()
            )

            for token_id in token_ids:
                snaps = list(
                    session.scalars(
                        select(OrderBookSnapshot)
                        .where(
                            OrderBookSnapshot.token_id == token_id,
                            OrderBookSnapshot.ts >= cutoff,
                        )
                        .order_by(OrderBookSnapshot.ts.asc(), OrderBookSnapshot.id.asc())
                    ).all()
                )
                if not snaps:
                    continue
                res, changes = self._run_token(
                    token_id, snaps[0].market_id, snaps, reward_map.get(token_id)
                )
                results.append(res)
                all_changes.extend(changes)

        starting_cash = self.params.starting_cash_usd
        net = sum(r.equity() for r in results)
        final_equity = starting_cash + net

        results.sort(key=lambda r: r.equity(), reverse=True)
        return MMReport(
            starting_cash=starting_cash,
            final_equity=final_equity,
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
