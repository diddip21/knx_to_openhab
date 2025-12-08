#!/usr/bin/env bash
set -euo pipefail

# Simple installer for DietPi / Raspberry Pi (no docker)
BASE="/opt/knx_to_openhab"
SERVICE_USER="knxui"
PYVER=$(python3 -c 'import sys; print("{}.{}".format(sys.version_info.major, sys.version_info.minor))')

echo "Creating service user"
if ! id -u $SERVICE_USER >/dev/null 2>&1; then
  sudo useradd -r -s /bin/bash -m $SERVICE_USER || true
fi

echo "Creating base dir $BASE"
sudo mkdir -p "$BASE"
sudo chown "$SERVICE_USER":"$SERVICE_USER" "$BASE"

echo "Creating python venv"
python3 -m venv "$BASE/venv"
"$BASE/venv/bin/pip" install --upgrade pip
"$BASE/venv/bin/pip" install -r "$(pwd)/requirements.txt"

echo "Copying files"
rsync -a --exclude .git . "$BASE/"

echo "Creating runtime dirs"
sudo mkdir -p /var/lib/knx_to_openhab
sudo mkdir -p /var/backups/knx_to_openhab
# Change ownership to service user for all directories
sudo chown -R "$SERVICE_USER":"$SERVICE_USER" "$BASE"
sudo chown -R "$SERVICE_USER":"$SERVICE_USER" /var/lib/knx_to_openhab /var/backups/knx_to_openhab

# Mark directory as safe for git (required since we change ownership)
sudo -u "$SERVICE_USER" git config --global --add safe.directory "$BASE"

echo "Creating service user"
if ! id -u $SERVICE_USER >/dev/null 2>&1; then
  sudo useradd -r -s /bin/bash -m $SERVICE_USER || true
fi

echo "Create sudoers entry for restarting services"
SUDOERS_FILE="/etc/sudoers.d/knxui"
echo "$SERVICE_USER ALL=(ALL) NOPASSWD: /bin/systemctl restart openhab.service, /bin/systemctl restart knxui.service" | sudo tee $SUDOERS_FILE
sudo chmod 440 $SUDOERS_FILE

echo "Installing systemd units and timers"
sudo cp installer/knxui.service /etc/systemd/system/knxui.service
sudo cp installer/knxui-backup-cleanup.service /etc/systemd/system/knxui-backup-cleanup.service
sudo cp installer/knxui-backup-cleanup.timer /etc/systemd/system/knxui-backup-cleanup.timer
sudo systemctl daemon-reload
sudo systemctl enable --now knxui.service || true
sudo systemctl enable --now knxui-backup-cleanup.timer || true

echo "Installation complete. Services installed:"
echo "  - knxui.service (Web UI)"
echo "  - knxui-backup-cleanup.timer (Daily backup cleanup)"
echo "Browse to http://$(hostname -I | awk '{print $1}'):8080"
