#!/usr/bin/env bash
#
# Current on-demand task, run at the end of `polybot-sync`.
#
# DEFAULT: print a health + data-collection status report. When Claude needs to
# perform a one-off action on the server (a query, a config tweak, a migration),
# it edits THIS file in the repo; the next `sudo polybot-sync` pulls and runs it.
#
APP_DIR=/opt/polybot
DB="$APP_DIR/data/polybot.db"

echo "================ polybot status ================"
if systemctl is-active --quiet polybot-collector; then
  echo "collector service : ACTIVE"
else
  echo "collector service : INACTIVE (!)"
fi

if command -v sqlite3 >/dev/null 2>&1; then
  snaps=$(sqlite3 "$DB" 'SELECT COUNT(*) FROM orderbook_snapshots;' 2>/dev/null)
  mkts=$(sqlite3 "$DB" 'SELECT COUNT(*) FROM markets;' 2>/dev/null)
  latest=$(sqlite3 "$DB" "SELECT datetime(MAX(ts),'unixepoch') FROM orderbook_snapshots;" 2>/dev/null)
  span=$(sqlite3 "$DB" "SELECT ROUND((MAX(ts)-MIN(ts))/3600.0,2) FROM orderbook_snapshots;" 2>/dev/null)
  rew=$(sqlite3 "$DB" 'SELECT COUNT(*) FROM markets WHERE rewards_enabled=1;' 2>/dev/null)
  sports=$(sqlite3 "$DB" "SELECT COUNT(*) FROM markets WHERE category='sports';" 2>/dev/null)
  avgspread=$(sqlite3 "$DB" "SELECT ROUND(AVG((best_ask-best_bid)*100),3) FROM orderbook_snapshots WHERE best_bid IS NOT NULL AND best_ask IS NOT NULL AND ts >= (SELECT MAX(ts)-60 FROM orderbook_snapshots);" 2>/dev/null)
  echo "snapshots         : ${snaps:-?}"
  echo "markets tracked   : ${mkts:-?}"
  echo "  reward-enabled  : ${rew:-?}"
  echo "  sports          : ${sports:-?}"
  echo "avg spread (last  : ${avgspread:-?} cents"
  echo "  60s, both sides)"
  echo "latest snap (UTC) : ${latest:-?}"
  echo "collection span   : ${span:-?} hours"
else
  echo "(install sqlite3 for data stats:  apt-get install -y sqlite3)"
fi

echo "db size           : $(du -h "$DB" 2>/dev/null | cut -f1)"
echo "disk free         : $(df -h / | awk 'NR==2{print $4" / "$2}')"
echo "current commit    : $(git -C "$APP_DIR" rev-parse --short HEAD 2>/dev/null)"
echo "================================================"

CFG="$APP_DIR/config/config.yaml"
[ -f "$CFG" ] || CFG="$APP_DIR/config/config.example.yaml"

# --- What does the collected data actually show? ---
echo
POLYBOT_DB_PATH="$DB" "$APP_DIR/.venv/bin/python" -m polybot.cli data-report --config "$CFG" 2>/dev/null || \
  echo "(data-report skipped)"

# --- Reward screener: where (if anywhere) is reward-farming worthwhile? ---
echo
POLYBOT_DB_PATH="$DB" "$APP_DIR/.venv/bin/python" -m polybot.cli screen --config "$CFG" 2>/dev/null || \
  echo "(screen skipped)"

# --- Professional MM backtest on the collected data (paper, no real orders) ---
echo
# Point the backtest at the real DB explicitly — polybot-sync does not cd into
# the project, so a relative db_path would open an empty database.
POLYBOT_DB_PATH="$DB" "$APP_DIR/.venv/bin/python" -m polybot.cli mm-backtest --config "$CFG" 2>/dev/null || \
  echo "(mm-backtest skipped — not enough data yet)"
