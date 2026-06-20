"""Human-readable report on what the collected data actually contains.

Answers the practical questions before trusting any backtest:
  * How much, how long, how evenly covered?
  * How wide are spreads really? (what a maker could earn)
  * How much do prices actually move? (adverse-selection risk / opportunity)
  * What kinds of markets are we tracking?
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Engine


def _scalar(conn, sql, **params):
    return conn.execute(text(sql), params).fetchone()


def build_data_report(engine: Engine) -> str:
    lines: list[str] = []
    add = lines.append

    with engine.connect() as conn:
        total, tokens, min_ts, max_ts = _scalar(
            conn,
            "SELECT COUNT(*), COUNT(DISTINCT token_id), MIN(ts), MAX(ts) "
            "FROM orderbook_snapshots",
        )
        if not total:
            return "No snapshots collected yet."
        span_h = (max_ts - min_ts) / 3600.0
        n_markets = _scalar(conn, "SELECT COUNT(*) FROM markets")[0]

        add("================ DATA REPORT ================")
        add(f"snapshots         : {total:,}")
        add(f"distinct tokens   : {tokens}")
        add(f"markets           : {n_markets}")
        add(f"time span         : {span_h:.2f} hours")
        add(f"avg snaps/token   : {total / tokens:.0f}")

        # --- Spread: what a maker could earn (over the whole dataset) ---
        smin, savg, smax = _scalar(
            conn,
            "SELECT MIN((best_ask-best_bid)*100), AVG((best_ask-best_bid)*100), "
            "MAX((best_ask-best_bid)*100) FROM orderbook_snapshots "
            "WHERE best_bid IS NOT NULL AND best_ask IS NOT NULL",
        )
        add("")
        add("--- spread (cents, both sides) ---")
        add(f"min / avg / max   : {smin:.2f} / {savg:.2f} / {smax:.2f}")

        # Spread distribution buckets.
        sb = _scalar(
            conn,
            "SELECT "
            " SUM(CASE WHEN s<0.2 THEN 1 ELSE 0 END), "
            " SUM(CASE WHEN s>=0.2 AND s<1 THEN 1 ELSE 0 END), "
            " SUM(CASE WHEN s>=1 AND s<3 THEN 1 ELSE 0 END), "
            " SUM(CASE WHEN s>=3 THEN 1 ELSE 0 END) "
            "FROM (SELECT (best_ask-best_bid)*100 AS s FROM orderbook_snapshots "
            "      WHERE best_bid IS NOT NULL AND best_ask IS NOT NULL)",
        )
        add(f"snaps <0.2c       : {sb[0] or 0:,}  (too tight to make money)")
        add(f"snaps 0.2-1c      : {sb[1] or 0:,}")
        add(f"snaps 1-3c        : {sb[2] or 0:,}  (workable for MM)")
        add(f"snaps >=3c        : {sb[3] or 0:,}  (wide)")

        # --- Movement: how much do mids actually move per token? ---
        mv = _scalar(
            conn,
            "SELECT "
            " SUM(CASE WHEN rng<1 THEN 1 ELSE 0 END), "
            " SUM(CASE WHEN rng>=1 AND rng<5 THEN 1 ELSE 0 END), "
            " SUM(CASE WHEN rng>=5 AND rng<15 THEN 1 ELSE 0 END), "
            " SUM(CASE WHEN rng>=15 THEN 1 ELSE 0 END), "
            " AVG(rng) "
            "FROM (SELECT token_id, (MAX((best_bid+best_ask)/2.0)-MIN((best_bid+best_ask)/2.0))*100 AS rng "
            "      FROM orderbook_snapshots WHERE best_bid IS NOT NULL AND best_ask IS NOT NULL "
            "      GROUP BY token_id)",
        )
        add("")
        add(f"--- price movement over {span_h:.1f}h (mid range per token, cents) ---")
        add(f"avg range/token   : {(mv[4] or 0):.1f}c")
        add(f"tokens moved <1c  : {mv[0] or 0}  (dead — no edge either way)")
        add(f"tokens moved 1-5c : {mv[1] or 0}")
        add(f"tokens moved 5-15c: {mv[2] or 0}")
        add(f"tokens moved >15c : {mv[3] or 0}  (volatile — adverse selection risk)")

        # --- Category breakdown ---
        add("")
        add("--- markets by category ---")
        for cat, cnt, rew in conn.execute(text(
            "SELECT category, COUNT(*), SUM(CASE WHEN rewards_enabled=1 THEN 1 ELSE 0 END) "
            "FROM markets GROUP BY category ORDER BY COUNT(*) DESC"
        )):
            add(f"{(cat or '?'):10s}: {cnt} markets ({rew or 0} reward-enabled)")

        # --- A few sample markets ---
        add("")
        add("--- sample markets (top volume) ---")
        for q, cat, rms, vol in conn.execute(text(
            "SELECT substr(question,1,38), category, rewards_max_spread, volume_usd "
            "FROM markets ORDER BY volume_usd DESC LIMIT 6"
        )):
            rms_s = f"{rms:.1f}c" if rms is not None else "-"
            add(f"[{(cat or '?')[:6]:6s}] reward<={rms_s:>5s} ${(vol or 0)/1e6:.1f}M  {q}")

        add("=============================================")
    return "\n".join(lines)
