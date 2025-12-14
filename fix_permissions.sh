#!/usr/bin/env bash
# Script to fix common permission issues for KNX to OpenHAB Generator

set -euo pipefail

# Configuration
INSTALL_DIR="/opt/knx_to_openhab"
SERVICE_USER="knxohui"

# Read backup directory from config (default to /var/backups/knx_to_openhab)
CONF="$INSTALL_DIR/web_ui/backend/config.json"
if [ -f "$CONF" ]; then
    BACKUP_DIR=$(python3 - <<PY
import json
import os
cfg=json.load(open('$CONF'))
backups_dir = cfg.get('backups_dir','/var/backups/knx_to_openhab')
# If it's a relative path, make it relative to the installation directory
if not backups_dir.startswith('/'):
    backups_dir = os.path.join('$INSTALL_DIR', backups_dir)
print(backups_dir)
PY
)
else
    BACKUP_DIR="/var/backups/knx_to_openhab"
fi

echo "Fixing permissions for KNX to OpenHAB Generator..."

# Ensure service user exists
if ! id -u $SERVICE_USER >/dev/null 2>&1; then
    echo "Service user $SERVICE_USER does not exist. Creating..."
    sudo useradd -r -s /bin/bash -m $SERVICE_USER
fi

# Fix ownership of installation directory
echo "Setting ownership for installation directory: $INSTALL_DIR"
sudo chown -R "$SERVICE_USER":"$SERVICE_USER" "$INSTALL_DIR"

# Fix ownership of backup directory
echo "Setting ownership for backup directory: $BACKUP_DIR"
sudo mkdir -p "$BACKUP_DIR"
sudo chown -R "$SERVICE_USER":"$SERVICE_USER" "$BACKUP_DIR"

# Fix git directory permissions specifically
echo "Setting proper permissions for git directory..."
sudo chown -R "$SERVICE_USER":"$SERVICE_USER" "$INSTALL_DIR/.git"
sudo chmod -R u+w "$INSTALL_DIR/.git"

# Mark directory as safe for git operations
echo "Marking directory as safe for git..."
sudo -u "$SERVICE_USER" git config --global --add safe.directory "$INSTALL_DIR" 2>/dev/null || true
sudo -u "$SERVICE_USER" git -C "$INSTALL_DIR" config --add safe.directory "$INSTALL_DIR" 2>/dev/null || true

# Ensure OpenHAB group permissions
echo "Ensuring OpenHAB group permissions..."
if ! getent group openhab > /dev/null 2>&1; then
    echo "Creating openhab group..."
    sudo groupadd openhab 2>/dev/null || true
fi
sudo usermod -a -G openhab $SERVICE_USER 2>/dev/null || true
if [ -d "/etc/openhab" ]; then
    sudo chmod -R 775 /etc/openhab 2>/dev/null || true
fi

# Check if sudoers entry exists
SUDOERS_FILE="/etc/sudoers.d/knxohui"
if [ ! -f "$SUDOERS_FILE" ]; then
    echo "Creating sudoers entry for $SERVICE_USER..."
    # Create sudoers entry for required commands
    CMDS="/bin/systemctl restart openhab.service, /usr/bin/systemctl restart openhab.service"
    CMDS="$CMDS, /bin/systemctl restart knxohui.service, /usr/bin/systemctl restart knxohui.service"
    CMDS="$CMDS, /bin/systemctl is-active openhab.service, /usr/bin/systemctl is-active openhab.service"
    CMDS="$CMDS, /bin/systemctl is-active knxohui.service, /usr/bin/systemctl is-active knxohui.service"
    CMDS="$CMDS, /bin/systemctl show openhab.service *, /usr/bin/systemctl show openhab.service *"
    CMDS="$CMDS, /bin/systemctl show knxohui.service *, /usr/bin/systemctl show knxohui.service *"
    CMDS="$CMDS, /usr/bin/git *"
    
    echo "$SERVICE_USER ALL=(ALL) NOPASSWD: $CMDS" | sudo tee $SUDOERS_FILE
    sudo chmod 440 $SUDOERS_FILE
fi

echo "Permissions fixed successfully!"
echo ""
echo "You can now run updates with the web UI or by executing:"
echo "  cd $INSTALL_DIR && ./update.sh"