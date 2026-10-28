#!/usr/bin/env bash
# Script to fix common permission issues for KNX to OpenHAB Generator

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="${KNXOH_INSTALL_DIR:-$(PYTHONPATH="$SCRIPT_DIR" python3 -c \
    'from knxoh_paths import get_paths; print(get_paths().install_dir)')}"
SERVICE_USER="knxohui"
BACKUP_DIR="${KNXOH_BACKUP_DIR:-$(PYTHONPATH="$INSTALL_DIR" python3 -c \
    'from knxoh_paths import get_paths; print(get_paths().backup_dir)')}"
DATA_DIR="${KNXOH_DATA_DIR:-$(PYTHONPATH="$INSTALL_DIR" python3 -c \
    'from knxoh_paths import get_paths; print(get_paths().data_dir)')}"

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

# Fix ownership of external runtime data (jobs, uploads, staging, generated config)
echo "Setting ownership for runtime data directory: $DATA_DIR"
sudo mkdir -p "$DATA_DIR"
sudo chown -R "$SERVICE_USER":"$SERVICE_USER" "$DATA_DIR"

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
PYTHON="$INSTALL_DIR/venv/bin/python"
if [ ! -x "$PYTHON" ]; then
    PYTHON="python3"
fi
sudo "$PYTHON" "$INSTALL_DIR/installer/provision_managed_files.py" \
    --service-user "$SERVICE_USER" --openhab-group openhab

# Install the package helper outside the service user's writable application tree.
if [[ -f "$INSTALL_DIR/installer/service_update.sh" ]]; then
    sudo install -o root -g root -m 0755 \
        "$INSTALL_DIR/installer/service_update.sh" \
        /usr/local/sbin/knxohui-service-update
fi
sudo install -d -o root -g root -m 0755 /usr/local/libexec/knx_to_openhab
sudo install -o root -g root -m 0755 \
    "$INSTALL_DIR/installer/provision_managed_outputs.py" \
    /usr/local/libexec/knx_to_openhab/provision_managed_outputs.py

# Replace the sudoers entry so repairs also remove obsolete broad permissions.
sudo bash "$INSTALL_DIR/installer/migrate_sudoers.sh"

echo "Permissions fixed successfully!"
echo ""
echo "You can now run updates with the web UI or by executing:"
echo "  cd $INSTALL_DIR && ./update.sh"
