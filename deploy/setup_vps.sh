#!/usr/bin/env bash
#
# One-shot setup for running the polybot collector as an always-on service on a
# fresh Debian/Ubuntu VPS. Read-only: it only collects public data, never trades.
#
# Usage (as root, or with sudo):
#   curl -fsSL ... | bash      # not recommended; review first
#   sudo bash deploy/setup_vps.sh
#
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/illiaonyshchuk86-byte/bot-polumarket-.git}"
BRANCH="${BRANCH:-claude/polymarket-trading-bot-94tz5l}"
APP_DIR="${APP_DIR:-/opt/polybot}"
SERVICE_USER="${SERVICE_USER:-polybot}"

echo "==> Installing system packages"
apt-get update -y
apt-get install -y python3 python3-venv python3-pip git

echo "==> Creating service user '${SERVICE_USER}'"
id -u "${SERVICE_USER}" >/dev/null 2>&1 || useradd --system --create-home --shell /usr/sbin/nologin "${SERVICE_USER}"

echo "==> Cloning repository into ${APP_DIR}"
if [ ! -d "${APP_DIR}/.git" ]; then
  git clone --branch "${BRANCH}" "${REPO_URL}" "${APP_DIR}"
else
  git -C "${APP_DIR}" fetch origin "${BRANCH}"
  git -C "${APP_DIR}" checkout "${BRANCH}"
  git -C "${APP_DIR}" pull origin "${BRANCH}"
fi

echo "==> Creating virtualenv and installing polybot"
python3 -m venv "${APP_DIR}/.venv"
"${APP_DIR}/.venv/bin/pip" install --upgrade pip
"${APP_DIR}/.venv/bin/pip" install -e "${APP_DIR}"

echo "==> Preparing config and data directory"
mkdir -p "${APP_DIR}/data"
[ -f "${APP_DIR}/config/config.yaml" ] || cp "${APP_DIR}/config/config.example.yaml" "${APP_DIR}/config/config.yaml"
chown -R "${SERVICE_USER}:${SERVICE_USER}" "${APP_DIR}"

echo "==> Installing systemd service"
install -m 0644 "${APP_DIR}/deploy/polybot-collector.service" /etc/systemd/system/polybot-collector.service
systemctl daemon-reload
systemctl enable --now polybot-collector.service

echo "==> Done. Useful commands:"
echo "    systemctl status polybot-collector"
echo "    journalctl -u polybot-collector -f"
echo "    sqlite3 ${APP_DIR}/data/polybot.db 'SELECT COUNT(*) FROM orderbook_snapshots;'"
