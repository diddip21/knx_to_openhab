#!/usr/bin/env bash
set -euo pipefail

# Simple installer for DietPi / Raspberry Pi (no docker)
BASE="/opt/knx_to_openhab"
SERVICE_USER="knxohui"
PYVER=$(python3 -c 'import sys; print("{}.{}".format(sys.version_info.major, sys.version_info.minor))')

echo "Creating service user"
# Create group first if it doesn't exist
if ! getent group $SERVICE_USER >/dev/null 2>&1; then
  sudo groupadd -r $SERVICE_USER
fi
# Create user with the group (whether it existed before or not)
if ! id -u $SERVICE_USER >/dev/null 2>&1; then
  sudo useradd -r -g $SERVICE_USER -s /bin/bash -m $SERVICE_USER
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
CONF="$BASE/web_ui/backend/config.json"
if [ -f "$CONF" ]; then
    JOBS_DIR=$(python3 -c "import json; print(json.load(open('$CONF')).get('jobs_dir', 'var/lib/knx_to_openhab'))" 2>/dev/null || echo "var/lib/knx_to_openhab")
    BACKUPS_DIR=$(python3 -c "import json; print(json.load(open('$CONF')).get('backups_dir', 'var/backups/knx_to_openhab'))" 2>/dev/null || echo "var/backups/knx_to_openhab")
    PORT=$(python3 -c "import json; print(json.load(open('$CONF')).get('port', 8085))" 2>/dev/null || echo "8085")
else
    JOBS_DIR="var/lib/knx_to_openhab"
    BACKUPS_DIR="var/backups/knx_to_openhab"
    PORT="8085"
fi

# If paths are relative, make them absolute with respect to BASE
if [[ "$JOBS_DIR" != /* ]]; then
    JOBS_DIR="$BASE/$JOBS_DIR"
fi

if [[ "$BACKUPS_DIR" != /* ]]; then
    BACKUPS_DIR="$BASE/$BACKUPS_DIR"
fi

echo "Creating runtime dirs"
sudo mkdir -p "$JOBS_DIR"
sudo mkdir -p "$BACKUPS_DIR"
# Change ownership to service user for all directories
sudo chown -R "$SERVICE_USER":"$SERVICE_USER" "$BASE"
sudo chown -R "$SERVICE_USER":"$SERVICE_USER" "$JOBS_DIR" "$BACKUPS_DIR"

# Mark directory as safe for git (required since we change ownership)
sudo -u "$SERVICE_USER" git config --global --add safe.directory "$BASE"

# Also mark the specific directory as safe (for newer git versions)
sudo -u "$SERVICE_USER" git -C "$BASE" config --add safe.directory "$BASE" 2>/dev/null || true

echo "Setting up group permissions for OpenHAB access"
# Check if openhab group exists, create if needed
if ! getent group openhab > /dev/null 2>&1; then
    sudo groupadd openhab
fi
# Add knxohui user to openhab group
sudo usermod -a -G openhab $SERVICE_USER
# Set proper permissions on OpenHAB directory if it exists
if [ -d "/etc/openhab" ]; then
    sudo chmod -R 775 /etc/openhab 2>/dev/null || true
fi

echo "Create sudoers entry for restarting services and git operations"
SUDOERS_FILE="/etc/sudoers.d/knxohui"
# Allow both /bin/systemctl and /usr/bin/systemctl to cover different OS layouts
# Allow restart, is-active, and show (for uptime info)
CMDS="/bin/systemctl restart openhab.service, /usr/bin/systemctl restart openhab.service"
CMDS="$CMDS, /bin/systemctl restart knxohui.service, /usr/bin/systemctl restart knxohui.service"
CMDS="$CMDS, /bin/systemctl is-active openhab.service, /usr/bin/systemctl is-active openhab.service"
CMDS="$CMDS, /bin/systemctl is-active knxohui.service, /usr/bin/systemctl is-active knxohui.service"
CMDS="$CMDS, /bin/systemctl show openhab.service *, /usr/bin/systemctl show openhab.service *"
CMDS="$CMDS, /bin/systemctl show knxohui.service *, /usr/bin/systemctl show knxohui.service *"
# Add git commands needed for updates
CMDS="$CMDS, /usr/bin/git *"

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
