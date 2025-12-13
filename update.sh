#!/usr/bin/env bash
# Self-update script for KNX to OpenHAB Generator
# This script is executed by the web UI when an update is requested

set -euo pipefail

# Configuration
INSTALL_DIR="/opt/knx_to_openhab"
LOG_FILE="${LOG_FILE:-/var/log/knx_to_openhab_update.log}"
BACKUP_DIR="/var/backups/knx_to_openhab"
SERVICE_NAME="knxohui.service"

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

# Check permissions
if [[ ! -w ".git" ]]; then
    log "ERROR: Permission denied. Cannot write to .git directory."
    log "The likely cause is incorrect file ownership."
    log "Please fix it by running:"
    log "  sudo chown -R knxohui:knxohui $INSTALL_DIR $BACKUP_DIR"
    exit 1
fi

if [[ -d "$BACKUP_DIR" ]] && [[ ! -w "$BACKUP_DIR" ]]; then
    log "ERROR: Permission denied. Cannot write to backup directory: $BACKUP_DIR"
    log "Please fix it by running:"
    log "  sudo chown -R knxohui:knxohui $BACKUP_DIR"
    exit 1
fi

# Create backup of current installation
log "Creating backup of current installation..."
BACKUP_NAME="pre-update-$(date +%Y%m%d-%H%M%S).tar.gz"
BACKUP_PATH="$BACKUP_DIR/$BACKUP_NAME"

mkdir -p "$BACKUP_DIR"
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
git -c safe.directory='*' stash || log "WARNING: Git stash failed"

# Fetch latest changes from GitHub
log "Fetching latest changes from GitHub..."
if ! git -c safe.directory='*' fetch origin; then
    log "ERROR: Failed to fetch from GitHub"
    exit 1
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
