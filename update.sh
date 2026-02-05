#!/usr/bin/env bash
# Self-update script for KNX to OpenHAB Generator
# This script is executed by the web UI when an update is requested

set -euo pipefail

# Configuration
# Resolve installation directory dynamically (can be overridden via INSTALL_DIR env var)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="${INSTALL_DIR:-$SCRIPT_DIR}"
LOG_FILE="${LOG_FILE:-/var/log/knx_to_openhab_update.log}"
SERVICE_NAME="knxohui.service"

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

# Logging function
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

log "========================================="
log "Starting KNX to OpenHAB Generator update"
log "========================================="

# Change to installation directory
if ! cd "$INSTALL_DIR"; then
    log "ERROR: Failed to change to $INSTALL_DIR"
    exit 1
fi

# Ensure proper group permissions for OpenHAB access
log "Ensuring OpenHAB group permissions..."
# Check if openhab group exists, create if needed
if ! getent group openhab > /dev/null 2>&1; then
    sudo groupadd openhab 2>/dev/null || true
fi
# Add knxohui user to openhab group
sudo usermod -a -G openhab knxohui 2>/dev/null || true
# Set proper permissions on OpenHAB directory if it exists
if [ -d "/etc/openhab" ]; then
    sudo chmod -R 775 /etc/openhab 2>/dev/null || true
fi

# Check permissions and attempt to fix them if needed
if [[ ! -w ".git" ]]; then
    log "Permission issue detected with .git directory."
    log "Attempting to fix file ownership..."
    if sudo chown -R knxohui:knxohui "$INSTALL_DIR/.git" 2>/dev/null; then
        log "Git directory ownership fixed successfully."
    else
        log "ERROR: Permission denied. Cannot write to .git directory."
        log "The likely cause is incorrect file ownership."
        log "Please fix it by running:"
        log "  sudo chown -R knxohui:knxohui $INSTALL_DIR $BACKUP_DIR"
        exit 1
    fi
fi

if [[ -d "$BACKUP_DIR" ]] && [[ ! -w "$BACKUP_DIR" ]]; then
    log "Permission issue detected with backup directory."
    log "Attempting to fix backup directory ownership..."
    if sudo chown -R knxohui:knxohui "$BACKUP_DIR" 2>/dev/null; then
        log "Backup directory ownership fixed successfully."
    else
        log "ERROR: Permission denied. Cannot write to backup directory: $BACKUP_DIR"
        log "Please fix it by running:"
        log "  sudo chown -R knxohui:knxohui $BACKUP_DIR"
        exit 1
    fi
fi

# Mark the installation directory as safe for git operations
log "Ensuring git directory is marked as safe..."
sudo -u knxohui git config --global --add safe.directory "$INSTALL_DIR" 2>/dev/null || true

# If backup directory doesn't exist, create it with proper permissions
if [[ ! -d "$BACKUP_DIR" ]]; then
    log "Creating backup directory: $BACKUP_DIR"
    mkdir -p "$BACKUP_DIR" || {
        log "ERROR: Failed to create backup directory: $BACKUP_DIR"
        log "Please ensure you have proper permissions or create the directory manually:"
        log "  sudo mkdir -p $BACKUP_DIR"
        log "  sudo chown -R knxohui:knxohui $BACKUP_DIR"
        exit 1
    }
fi

# Create backup of current installation
log "Creating backup of current installation..."
BACKUP_NAME="pre-update-$(date +%Y%m%d-%H%M%S).tar.gz"
BACKUP_PATH="$BACKUP_DIR/$BACKUP_NAME"

# Ensure backup directory exists with proper permissions
if [[ ! -d "$BACKUP_DIR" ]]; then
    log "Creating backup directory: $BACKUP_DIR"
    mkdir -p "$BACKUP_DIR" || {
        log "ERROR: Failed to create backup directory: $BACKUP_DIR"
        log "Please ensure you have proper permissions or create the directory manually:"
        log "  sudo mkdir -p $BACKUP_DIR"
        log "  sudo chown -R knxohui:knxohui $BACKUP_DIR"
        exit 1
    }
fi

tar -czf "$BACKUP_PATH" \
    --exclude='.git' \
    --exclude='venv' \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='var' \
    . || {
log "WARNING: Backup creation failed, but continuing..."
}

if [[ -f "$BACKUP_PATH" ]]; then
    log "Backup created: $BACKUP_PATH"
else
    log "WARNING: Backup file not created"
fi

# Stash any local changes
log "Stashing local changes..."
if ! git -c safe.directory='*' stash; then
    log "WARNING: Git stash failed, continuing anyway..."
fi

# Verify git repository is properly configured
log "Verifying git repository configuration..."
if ! git -c safe.directory='*' rev-parse --git-dir > /dev/null 2>&1; then
    log "ERROR: Not a valid git repository or access denied."
    log "Please verify the installation directory and permissions."
    exit 1
fi

# Mark directory as safe if not already done
sudo -u knxohui git config --global --add safe.directory "$INSTALL_DIR" 2>/dev/null || true

# Fetch latest changes from GitHub
log "Fetching latest changes from GitHub..."
if ! git -c safe.directory='*' fetch origin; then
    log "Attempting to fix git permissions and retry..."
    # Try to fix common git permission issues
    sudo chown -R knxohui:knxohui "$INSTALL_DIR/.git" 2>/dev/null || true
    sudo chmod -R u+w "$INSTALL_DIR/.git" 2>/dev/null || true
    
    # Retry the fetch operation
    if ! git -c safe.directory='*' fetch origin; then
        log "ERROR: Failed to fetch from GitHub after permission fix attempts"
        exit 1
    fi
    log "Successfully fetched after fixing permissions"
fi

# Get current and remote commit hashes
CURRENT_COMMIT=$(git -c safe.directory='*' rev-parse HEAD)
REMOTE_COMMIT=$(git -c safe.directory='*' rev-parse origin/main)

log "Current commit: $CURRENT_COMMIT"
log "Remote commit: $REMOTE_COMMIT"

if [[ "$CURRENT_COMMIT" == "$REMOTE_COMMIT" ]]; then
    log "Already up to date!"
    exit 0
fi

# Pull latest changes
log "Pulling latest changes..."
if ! git -c safe.directory='*' pull origin main; then
    log "ERROR: Git pull failed"
    log "Attempting to restore from backup..."
    git -c safe.directory='*' reset --hard "$CURRENT_COMMIT"
    exit 1
fi

# Update Python dependencies
log "Updating Python dependencies..."
if [[ -f "$INSTALL_DIR/venv/bin/pip" ]]; then
    "$INSTALL_DIR/venv/bin/pip" install --upgrade pip -q || log "WARNING: pip upgrade failed"
    if ! "$INSTALL_DIR/venv/bin/pip" install -r requirements.txt -q; then
        log "ERROR: Failed to install dependencies"
        log "Attempting to restore from backup..."
        git -c safe.directory='*' reset --hard "$CURRENT_COMMIT"
        exit 1
    fi
else
    log "WARNING: Virtual environment not found, skipping dependency update"
fi

# Update version.json with new commit hash
log "Updating version.json..."
NEW_COMMIT=$(git -c safe.directory='*' rev-parse HEAD)
if [[ -f "version.json" ]]; then
    # Use Python to update the JSON file
    python3 -c "
import json
with open('version.json', 'r') as f:
    data = json.load(f)
data['commit_hash'] = '$NEW_COMMIT'
data['build_date'] = '$(date +%Y-%m-%d)'
with open('version.json', 'w') as f:
    json.dump(data, f, indent=2)
" || log "WARNING: Failed to update version.json"
fi

# Restart the service
log "Restarting $SERVICE_NAME..."
if ! sudo systemctl restart "$SERVICE_NAME"; then
    log "ERROR: Failed to restart service"
    log "Service may need manual restart: sudo systemctl restart $SERVICE_NAME"
    exit 1
fi

# Wait a moment for service to start
sleep 2

# Check if service is running
if sudo systemctl is-active --quiet "$SERVICE_NAME"; then
    log "Service restarted successfully"
else
    log "WARNING: Service may not be running properly"
    log "Check status with: sudo systemctl status $SERVICE_NAME"
fi

log "========================================="
log "Update completed successfully!"
log "New commit: $NEW_COMMIT"
log "Backup saved to: $BACKUP_PATH"
log "========================================="

exit 0
