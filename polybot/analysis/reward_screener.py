"""Multi-factor reward screener.

For each collected market it estimates, from REAL data, whether quoting there to
farm liquidity rewards is worthwhile, accounting for:

  * reward pool      — rewards_daily_rate ($/day) from the API
  * competition      — book depth in the reward zone (the share denominator)
  * our share        — from the reward model, for a standard capital deployment
  * volatility       — mid-price stdev over the collected window (adverse-selection risk)
  * time to resolve  — days until endDate (reward stream ends / gap risk)
  * liquidity        — how much can realistically be deployed

It then produces a transparent, rule-based verdict per market. Nothing here is
annualized and rewards use the conservative competition estimate.
"""

from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass

from sqlalchemy import func, select, text
from sqlalchemy.engine import Engine

from ..config import ScreenerConfig
from ..domain import Quote
from ..paper.rewards import RewardParams, book_score, quote_score
from ..storage.db import make_session_factory, snapshot_to_book
from ..storage.models import Market, OrderBookSnapshot


@dataclass
class MarketScore:
    market_id: str
    question: str
    category: str
    pool_daily: float
    mid: float
    spread_cents: float
    competition: float
    our_share_pct: float
    expected_reward_daily: float
    reward_yield_pct: float        # %/day on deployed capital, from rewards only
    vol_cents: float               # mid stdev (adverse-selection risk proxy)
    range_cents: float             # mid max-min over window
    days_to_resolution: float | None
    liquidity_usd: float
    verdict: str
    risk_adj_yield: float          # ranking metric


def _verdict(
    cfg: ScreenerConfig, *, pool: float, qualifies: bool, yield_pct: float,
    vol_cents: float, days: float | None,
) -> str:
    if pool <= 0:
        return "NO-REWARD"
    if not qualifies:
        return "UNDERFUNDED"          # capital too small to meet rewards_min_size
    if days is not None and days < cfg.min_days_to_resolution:
        return "RESOLVES-SOON"
    if yield_pct < cfg.min_reward_yield_pct:
        return "LOW-YIELD"
    if vol_cents > cfg.max_vol_cents:
        return "HIGH-VOL"
    return "ATTRACTIVE"


def score_markets(engine: Engine, cfg: ScreenerConfig) -> list[MarketScore]:
    Session = make_session_factory(engine)
    now = time.time()
    out: list[MarketScore] = []

    with Session() as session:
        # Per-token volatility aggregates in one pass.
        agg: dict[str, tuple] = {}
        for row in session.execute(text(
            "SELECT token_id, COUNT(*) n, "
            " AVG((best_bid+best_ask)/2.0) avg_mid, "
            " AVG(((best_bid+best_ask)/2.0)*((best_bid+best_ask)/2.0)) avg_mid2, "
            " MIN((best_bid+best_ask)/2.0) min_mid, MAX((best_bid+best_ask)/2.0) max_mid "
            "FROM orderbook_snapshots "
            "WHERE best_bid IS NOT NULL AND best_ask IS NOT NULL GROUP BY token_id"
        )):
            agg[row.token_id] = (row.n, row.avg_mid, row.avg_mid2, row.min_mid, row.max_mid)

        # Latest snapshot per token (for current book -> competition).
        sub = (
            select(OrderBookSnapshot.token_id, func.max(OrderBookSnapshot.ts).label("mts"))
            .group_by(OrderBookSnapshot.token_id)
            .subquery()
        )
        latest: dict[str, OrderBookSnapshot] = {}
        for snap in session.scalars(
            select(OrderBookSnapshot).join(
                sub,
                (OrderBookSnapshot.token_id == sub.c.token_id)
                & (OrderBookSnapshot.ts == sub.c.mts),
            )
        ):
            latest[snap.token_id] = snap

        for m in session.scalars(select(Market)):
            try:
                token_ids = [str(t) for t in json.loads(m.clob_token_ids)]
            except (json.JSONDecodeError, TypeError):
                token_ids = []
            if not token_ids or token_ids[0] not in latest:
                continue
            tok = token_ids[0]
            book = snapshot_to_book(latest[tok])
            mid = book.midpoint()
            bb, ba = book.best_bid(), book.best_ask()
            if mid is None or bb is None or ba is None:
                continue
            spread_cents = (ba - bb) * 100.0

            params = RewardParams(
                m.rewards_max_spread or 0.0, m.rewards_min_size or 0.0, m.rewards_daily_rate or 0.0
            )

            # Our standard deployment: `capital` worth of shares on each side.
            shares = cfg.capital_per_market_usd / mid if mid > 0 else 0.0
            qualifies = params.min_size <= 0 or shares >= params.min_size
            d = cfg.quote_distance_cents / 100.0
            our_quote = Quote(
                bid_price=round(mid - d, 2), bid_size=shares,
                ask_price=round(mid + d, 2), ask_size=shares,
            )
            our_q = quote_score(our_quote, mid, params) if qualifies else 0.0
            comp = book_score(book, mid, params)
            share = our_q / (our_q + comp) if (our_q + comp) > 0 else 0.0
            exp_reward = share * params.daily_rate_usd
            yield_pct = 100.0 * exp_reward / cfg.capital_per_market_usd if cfg.capital_per_market_usd else 0.0

            # Volatility from aggregates.
            vol_cents = range_cents = 0.0
            if tok in agg:
                n, avg_mid, avg_mid2, min_mid, max_mid = agg[tok]
                if n and avg_mid is not None:
                    var = max(0.0, (avg_mid2 or 0.0) - avg_mid * avg_mid)
                    vol_cents = math.sqrt(var) * 100.0
                    range_cents = ((max_mid or 0.0) - (min_mid or 0.0)) * 100.0

            days = (m.end_ts - now) / 86400.0 if m.end_ts and m.end_ts > 0 else None

            verdict = _verdict(
                cfg, pool=params.daily_rate_usd, qualifies=qualifies,
                yield_pct=yield_pct, vol_cents=vol_cents, days=days,
            )
            risk_adj = yield_pct / (1.0 + vol_cents / max(cfg.max_vol_cents, 1e-9))

            out.append(MarketScore(
                market_id=m.market_id, question=m.question, category=m.category or "?",
                pool_daily=params.daily_rate_usd, mid=mid, spread_cents=spread_cents,
                competition=comp, our_share_pct=share * 100.0,
                expected_reward_daily=exp_reward, reward_yield_pct=yield_pct,
                vol_cents=vol_cents, range_cents=range_cents, days_to_resolution=days,
                liquidity_usd=m.liquidity_usd or 0.0, verdict=verdict, risk_adj_yield=risk_adj,
            ))

    out.sort(key=lambda s: (s.risk_adj_yield, s.reward_yield_pct), reverse=True)
    return out


def build_screener_report(engine: Engine, cfg: ScreenerConfig) -> str:
    scores = score_markets(engine, cfg)
    if not scores:
        return "No scored markets (need collected snapshots with reward data)."

    rewarded = [s for s in scores if s.pool_daily > 0]
    attractive = [s for s in scores if s.verdict == "ATTRACTIVE"]

    lines = ["============== REWARD SCREENER ==============",
             f"capital/market ${cfg.capital_per_market_usd:,.0f}  quote {cfg.quote_distance_cents}c "
             f"from mid  |  markets scored: {len(scores)}  with rewards: {len(rewarded)}",
             f"ATTRACTIVE: {len(attractive)}",
             "",
             f"{'yield%/d':>8} {'share%':>7} {'$rw/d':>7} {'pool$':>7} {'vol_c':>6} "
             f"{'d→res':>6} {'verdict':<13} market"]

    for s in scores[:25]:
        if s.pool_daily <= 0:
            continue
        days = f"{s.days_to_resolution:.1f}" if s.days_to_resolution is not None else "  -"
        lines.append(
            f"{s.reward_yield_pct:8.3f} {s.our_share_pct:7.3f} {s.expected_reward_daily:7.2f} "
            f"{s.pool_daily:7.0f} {s.vol_cents:6.2f} {days:>6} {s.verdict:<13} {s.question[:34]}"
        )

    lines.append("")
    if attractive:
        lines.append("Best opportunities (ATTRACTIVE):")
        for s in attractive[:5]:
            lines.append(f"  +${s.expected_reward_daily:.2f}/day ({s.reward_yield_pct:.2f}%/d) "
                         f"share {s.our_share_pct:.2f}%  {s.question[:40]}")
    else:
        lines.append("No ATTRACTIVE markets — competition/vol/timing kills the edge here.")
        lines.append("(This is the honest answer if it holds across more markets.)")
    lines.append("=============================================")
    return "\n".join(lines)
