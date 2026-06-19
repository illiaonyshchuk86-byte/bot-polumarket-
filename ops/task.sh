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
  echo "snapshots         : ${snaps:-?}"
  echo "markets tracked   : ${mkts:-?}"
  echo "latest snap (UTC) : ${latest:-?}"
  echo "collection span   : ${span:-?} hours"
else
  echo "(install sqlite3 for data stats:  apt-get install -y sqlite3)"
fi

echo "db size           : $(du -h "$DB" 2>/dev/null | cut -f1)"
echo "disk free         : $(df -h / | awk 'NR==2{print $4" / "$2}')"
echo "current commit    : $(git -C "$APP_DIR" rev-parse --short HEAD 2>/dev/null)"
echo "================================================"
