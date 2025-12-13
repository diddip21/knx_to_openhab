#!/usr/bin/env bash
set -euo pipefail

# Simple installer for DietPi / Raspberry Pi (no docker)
BASE="/opt/knx_to_openhab"
SERVICE_USER="knxohui"
PYVER=$(python3 -c 'import sys; print("{}.{}".format(sys.version_info.major, sys.version_info.minor))')

echo "Creating service user"
if ! id -u $SERVICE_USER >/dev/null 2>&1; then
  sudo useradd -r -s /bin/bash -m $SERVICE_USER || true
fi

echo "Creating base dir $BASE"
sudo mkdir -p "$BASE"
sudo chown "$USER":"$USER" "$BASE"

echo "Creating python venv"
python3 -m venv "$BASE/venv"
"$BASE/venv/bin/pip" install --upgrade pip
"$BASE/venv/bin/pip" install -r "$(pwd)/requirements.txt"

echo "Copying files"
rsync -a --exclude .git . "$BASE/"

# Read config values
CONF="web_ui/backend/config.json"
if [ -f "$CONF" ]; then
    JOBS_DIR=$(python3 -c "import json; print(json.load(open('$CONF')).get('jobs_dir', '/var/lib/knx_to_openhab'))" 2>/dev/null || echo "/var/lib/knx_to_openhab")
    BACKUPS_DIR=$(python3 -c "import json; print(json.load(open('$CONF')).get('backups_dir', '/var/backups/knx_to_openhab'))" 2>/dev/null || echo "/var/backups/knx_to_openhab")
    PORT=$(python3 -c "import json; print(json.load(open('$CONF')).get('port', 8085))" 2>/dev/null || echo "8085")
else
    JOBS_DIR="/var/lib/knx_to_openhab"
    BACKUPS_DIR="/var/backups/knx_to_openhab"
    PORT="8085"
fi

echo "Creating runtime dirs"
sudo mkdir -p "$JOBS_DIR"
sudo mkdir -p "$BACKUPS_DIR"
# Change ownership to service user for all directories
sudo chown -R "$SERVICE_USER":"$SERVICE_USER" "$BASE"
sudo chown -R "$SERVICE_USER":"$SERVICE_USER" "$JOBS_DIR" "$BACKUPS_DIR"

# Mark directory as safe for git (required since we change ownership)
sudo -u "$SERVICE_USER" git config --global --add safe.directory "$BASE"

echo "Creating service user"
if ! id -u $SERVICE_USER >/dev/null 2>&1; then
  sudo useradd -r -s /bin/bash -m $SERVICE_USER || true
fi

echo "Create sudoers entry for restarting services"
SUDOERS_FILE="/etc/sudoers.d/knxohui"
# Allow both /bin/systemctl and /usr/bin/systemctl to cover different OS layouts
# Allow restart, is-active, and show (for uptime info)
CMDS="/bin/systemctl restart openhab.service, /usr/bin/systemctl restart openhab.service"
CMDS="$CMDS, /bin/systemctl restart knxohui.service, /usr/bin/systemctl restart knxohui.service"
CMDS="$CMDS, /bin/systemctl is-active openhab.service, /usr/bin/systemctl is-active openhab.service"
CMDS="$CMDS, /bin/systemctl is-active knxohui.service, /usr/bin/systemctl is-active knxohui.service"
CMDS="$CMDS, /bin/systemctl show openhab.service *, /usr/bin/systemctl show openhab.service *"
CMDS="$CMDS, /bin/systemctl show knxohui.service *, /usr/bin/systemctl show knxohui.service *"

echo "$SERVICE_USER ALL=(ALL) NOPASSWD: $CMDS" | sudo tee $SUDOERS_FILE
sudo chmod 440 $SUDOERS_FILE

echo "Installing systemd units and timers"
sudo cp installer/knxohui.service /etc/systemd/system/knxohui.service
sudo cp installer/knxohui-backup-cleanup.service /etc/systemd/system/knxohui-backup-cleanup.service
sudo cp installer/knxohui-backup-cleanup.timer /etc/systemd/system/knxohui-backup-cleanup.timer
sudo systemctl daemon-reload
sudo systemctl enable --now knxohui.service || true
sudo systemctl enable --now knxohui-backup-cleanup.timer || true

echo "Installation complete. Services installed:"
echo "  - knxohui.service (Web UI)"
echo "  - knxohui-backup-cleanup.timer (Daily backup cleanup)"
echo "Browse to http://$(hostname -I | awk '{print $1}'):$PORT"
