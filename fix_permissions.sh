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

# Install the package helper outside the service user's writable application tree.
if [[ -f "$INSTALL_DIR/installer/service_update.sh" ]]; then
    sudo install -o root -g root -m 0755 \
        "$INSTALL_DIR/installer/service_update.sh" \
        /usr/local/sbin/knxohui-service-update
fi

# Replace the sudoers entry so repairs also remove obsolete broad permissions.
sudo bash "$INSTALL_DIR/installer/migrate_sudoers.sh"

echo "Permissions fixed successfully!"
echo ""
echo "You can now run updates with the web UI or by executing:"
echo "  cd $INSTALL_DIR && ./update.sh"
