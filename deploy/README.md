# Deploying the collector on an always-on VPS

The collector must run somewhere that stays on 24/7 to accumulate data over days
and weeks. This guide sets it up as a `systemd` service that auto-restarts on
crash or reboot. **Read-only: it collects public data only and never trades.**

## 1. Pick a VPS

Prices verified June 2026. A 1 GB / 1 vCPU box is plenty — the collector is tiny.

| Provider | Plan | Specs | ~Price/mo | Notes |
|---|---|---|---|---|
| **Hetzner** (recommended) | CAX11 (ARM) | 2 vCPU, 4 GB RAM, 40 GB | **~$3.79–4.99** | Best value; EU/US regions. Pick a region where Polymarket is **not** geoblocked. |
| Hetzner | CX22 (x86) | 2 vCPU, 4 GB RAM, ~20–40 GB | ~$4.59 | x86 if you need it. |
| Vultr | Regular | 1 vCPU, 1 GB RAM, 25 GB | ~$5 | 30+ regions, easy. |
| RackNerd | annual special | ~1 GB RAM | **~$1.25** (paid yearly) | Cheapest, but check stock/region. |

**Important — region & ToS:** put the VPS in a country where Polymarket is not
geoblocked, and do **not** use it to bypass geoblocking for real trading (that
violates Polymarket's ToS). For read-only public data collection this is just
about reaching the API reliably.

## 2. Automated setup

SSH into a fresh Debian/Ubuntu VPS, then:

```bash
sudo bash -c "$(curl -fsSL https://raw.githubusercontent.com/illiaonyshchuk86-byte/bot-polumarket-/claude/polymarket-trading-bot-94tz5l/deploy/setup_vps.sh)"
```

Or clone first and review before running (recommended):

```bash
git clone -b claude/polymarket-trading-bot-94tz5l \
  https://github.com/illiaonyshchuk86-byte/bot-polumarket-.git
sudo bash bot-polumarket-/deploy/setup_vps.sh
```

The script installs Python, creates a `polybot` service user, sets up a venv,
copies `config.example.yaml` → `config.yaml`, and starts the systemd service.

## 3. Manual setup (if you prefer)

```bash
sudo apt-get update && sudo apt-get install -y python3 python3-venv git
sudo git clone -b claude/polymarket-trading-bot-94tz5l \
  https://github.com/illiaonyshchuk86-byte/bot-polumarket-.git /opt/polybot
cd /opt/polybot
python3 -m venv .venv && .venv/bin/pip install -e .
cp config/config.example.yaml config/config.yaml
sudo cp deploy/polybot-collector.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now polybot-collector
```

## 4. Operate

```bash
systemctl status polybot-collector            # is it running?
journalctl -u polybot-collector -f            # live logs
sqlite3 /opt/polybot/data/polybot.db \
  'SELECT COUNT(*) FROM orderbook_snapshots;' # how much data so far
```

## 5. Data growth

With defaults (25 markets, 10 s polling, depth capped at 10 levels) expect
roughly **a few hundred MB per week** — a 25–40 GB disk lasts a long time. To
slow growth: raise `poll_interval_seconds`, lower `max_markets`, or lower
`max_book_depth` in `config.yaml`, then `systemctl restart polybot-collector`.

## 6. Backups

The SQLite file at `/opt/polybot/data/polybot.db` is the dataset. Copy it off
the box periodically (e.g. `scp` or a nightly cron) so a VPS failure doesn't
lose your history.
