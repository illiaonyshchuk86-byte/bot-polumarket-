# polybot — Polymarket data & paper-trading foundation

A research foundation for building a Polymarket trading bot. **Current stage:
read-only data + paper-trading (simulation) only.** It does **not** place real
orders and does **not** need a private key.

## ⚠️ Honest disclaimers (read first)

- **No profit promises.** There is no strategy here that is known to be
  profitable. Viral stories like "$313 → $414k in a month" are non-reproducible
  hype — do not build expectations on them.
- **Paper results overstate reality.** The simulator has no market impact, no
  latency, and no adverse selection, and assumes you can take displayed liquidity.
  Treat paper/backtest PnL as an optimistic upper bound, never a forecast.
- **The market is competitive.** Verified (June 2026): the average arbitrage
  opportunity lasts ~2.7s and most arbitrage profit is captured by sub-100ms
  bots. Market-making yields roughly ~1–3%/month with real inventory risk.
- **Legal / ToS.** Polymarket geoblocks by physical IP (OFAC-sanctioned
  jurisdictions plus several others). Bypassing geoblocks via VPN violates
  Polymarket's Terms of Service. This project does not help bypass them.
- **Beta upstream.** The official `polymarket-client` SDK is in beta and
  `py-clob-client` was archived (2026). For stability we read the public REST
  APIs directly; an authenticated SDK would only be needed for a future
  live-trading stage.

## What it does

| Module | Purpose |
|---|---|
| `polybot/clients/` | Read-only REST clients: Gamma (markets), CLOB (order books), Data API (positions/history). |
| `polybot/collector/` | Polls active markets + order books and stores snapshots in SQLite. |
| `polybot/paper/` | Simulated broker, portfolio, and a shared simulation session. |
| `polybot/backtest/` | Replays stored snapshots through a strategy. |
| `polybot/strategy/` | Pluggable strategy interface + two **demo** strategies. |
| `polybot/risk/` | Position limits, daily loss cap, kill switch — active even in paper mode. |

### Demo strategies (educational, not profitable)

- `arb_scanner` — flags intra-market YES/NO mispricings (`ask_yes + ask_no < $1`).
  **Alert only**, places no orders.
- `naive_mm` — quotes a fixed spread around the midpoint. Ignores inventory and
  adverse selection; exists only to exercise the order pipeline.

## Setup

```bash
python -m pip install -e .          # or: pip install -e ".[dev]" for tests
cp .env.example .env                # optional; defaults work out of the box
cp config/config.example.yaml config/config.yaml
```

## Usage

```bash
# 1) Collect live public data into SQLite (read-only)
python -m polybot.cli collect --minutes 3 --config config/config.yaml

# 2) Backtest a strategy on the collected snapshots
python -m polybot.cli backtest --strategy arb_scanner --config config/config.yaml

# 3) Paper-run a strategy live against real books (simulation only)
python -m polybot.cli paper-run --strategy naive_mm --minutes 2 --config config/config.yaml
```

## Tests

```bash
python -m pytest
```

Tests run entirely on recorded fixtures / in-memory SQLite — no network calls.

## Public API hosts (verified June 2026)

| API | Host |
|---|---|
| Gamma (market metadata) | `https://gamma-api.polymarket.com` |
| CLOB (order books / prices) | `https://clob.polymarket.com` |
| Data API (positions / history) | `https://data-api.polymarket.com` |
| WebSocket (market) | `wss://ws-subscriptions-clob.polymarket.com/ws/market` |

CLOB order-book reads (`/book`) were confirmed publicly accessible without
authentication during testing.

## Explicitly out of scope (for now)

- Placing real orders / using a private key.
- Bypassing geoblocks (violates ToS).
- Live auto-execution of arbitrage. This belongs to a later stage, only after a
  strategy proves itself in backtest and paper-trading.
