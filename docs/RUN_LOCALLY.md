# Running the MM bot locally (dry-run)

This is for testing on your own computer — **no server, no real orders, no
private key.** Everything is simulated against the real live market.

## 1. Install (once)

```bash
git clone -b claude/polymarket-trading-bot-94tz5l \
  https://github.com/illiaonyshchuk86-byte/bot-polumarket-.git
cd bot-polumarket-
python3 -m venv .venv && . .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -e .
cp config/config.example.yaml config/config.yaml
```

Requires Python 3.10+.

## 2. Live dry-run (the main test)

Runs the professional market maker against the **real live order book** in real
time, fully simulated:

```bash
python -m polybot.cli mm-dryrun --minutes 30 --interval 8 \
  --log runs/dry1.csv --config config/config.yaml
```

- `--minutes` how long to run · `--interval` seconds between polls ·
  `--log` writes the equity curve to CSV so you can review a long run · Ctrl-C stops cleanly.
- Each line shows live equity, PnL, fills, stand-asides (guards), max inventory.
- The final report is in **dollars and % of capital over the elapsed time —
  never annualized**, and **rewards are not credited**. Treat any profit as an
  honest floor.

## 3. Backtest on historical data (optional)

If you also collect data (`python -m polybot.cli collect --minutes 60`), you can
replay it through the exact same MM logic:

```bash
python -m polybot.cli mm-backtest --config config/config.yaml
```

## 4. Tuning — change numbers, never logic

All knobs live under `strategy.pro_mm` in `config.yaml`. The core logic in
`polybot/strategy/pro_mm.py` stays fixed. Tune over many runs, one change at a
time, and keep each change as a separate commit so you can always roll back:

| Knob | Effect | If you're bleeding from… |
|---|---|---|
| `min_half_spread_cents` | hard spread floor | …too-tight quotes → raise it |
| `base_half_spread_cents` | baseline spread | …adverse selection → raise it |
| `vol_spread_coeff` | widen on volatility | …moves → raise it |
| `jump_kill_cents` | pull quotes on a move | …getting run over → lower it |
| `inventory_skew_cents_per_share` | unload inventory faster | …inventory pile-up → raise it |
| `max_inventory_shares` | hard position cap | …big positions → lower it |
| `warmup_ticks` | wait before quoting | …bad early fills → raise it |
| `fill_through_ticks` | stricter fills (realism) | want a more conservative sim → raise it |

## What the simulation does and does NOT model

- ✅ Quotes from the current book; fills only from real subsequent moves
  (adverse selection is inherent).
- ✅ Tick size, min order size, inventory caps, volatility guard.
- ❌ Queue position, partial fills, sub-interval microstructure.
- ❌ Liquidity / maker / holding rewards (never credited — pure upside in reality).

So real results would differ — but this errs toward honesty, not optimism.
