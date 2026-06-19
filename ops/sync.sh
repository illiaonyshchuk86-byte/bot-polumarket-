#!/usr/bin/env bash
#
# polybot-sync: pull the latest code/ops from GitHub, update deps, restart the
# collector, then run the current ops/task.sh. Run as root:  sudo polybot-sync
#
# This is the "one-command mode" control channel: Claude prepares changes in the
# GitHub repo; you apply them by running this single command when asked.
#
set -euo pipefail

APP_DIR=/opt/polybot
BRANCH=claude/polymarket-trading-bot-94tz5l
SERVICE=polybot-collector

echo "==> polybot-sync starting $(date -u '+%Y-%m-%d %H:%M:%S UTC')"

# Git may complain about dubious ownership (repo owned by the polybot user).
git config --global --add safe.directory "$APP_DIR" 2>/dev/null || true

echo "==> Pulling latest code"
git -C "$APP_DIR" fetch --quiet origin "$BRANCH"
git -C "$APP_DIR" checkout --quiet "$BRANCH"
git -C "$APP_DIR" pull --ff-only origin "$BRANCH"

echo "==> Updating dependencies (if changed)"
"$APP_DIR/.venv/bin/pip" install -q -e "$APP_DIR"

# Re-assert ownership (pull/pip as root may have created root-owned files).
chown -R polybot:polybot "$APP_DIR" 2>/dev/null || true

echo "==> Restarting collector"
systemctl restart "$SERVICE"
sleep 2
if systemctl is-active --quiet "$SERVICE"; then
  echo "==> Collector restarted OK"
else
  echo "==> WARNING: collector is not active — recent logs:"
  journalctl -u "$SERVICE" -n 15 --no-pager || true
fi

# Run the current task (default: status report).
if [ -f "$APP_DIR/ops/task.sh" ]; then
  echo
  bash "$APP_DIR/ops/task.sh" || true
fi

echo "==> polybot-sync done"
