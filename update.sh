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

# State
BACKUP_PATH=""
CURRENT_COMMIT=""
NEW_COMMIT=""

# Logging function
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

log_step() {
    local step="$1"
    local total="$2"
    local message="$3"
    log "[${step}/${total}] $message"
}

fatal() {
    log "ERROR: $1"
    if [[ -n "$BACKUP_PATH" ]]; then
        log "Rollback instructions:"
        log "  1) Restore backup: sudo tar -xzf '$BACKUP_PATH' -C '$INSTALL_DIR'"
        if [[ -n "$CURRENT_COMMIT" ]]; then
            log "  2) Reset git: cd '$INSTALL_DIR' && git -c safe.directory='*' reset --hard '$CURRENT_COMMIT'"
        fi
        log "  3) Restart service: sudo systemctl restart $SERVICE_NAME"
    else
        log "Rollback instructions: No backup was created. Please check permissions and re-run the update."
    fi
    exit 1
}

trap 'fatal "Update failed unexpectedly at line $LINENO."' ERR

log "========================================="
log "Starting KNX to OpenHAB Generator update"
log "========================================="

log_step 1 6 "Pre-flight checks"

# Verify installation directory
if [[ ! -d "$INSTALL_DIR" ]]; then
    fatal "Installation directory not found: $INSTALL_DIR"
fi

# Ensure we are in a git repository
if [[ ! -d "$INSTALL_DIR/.git" ]]; then
    fatal "No git repository found in $INSTALL_DIR. Is this a valid installation?"
fi

# Ensure python3 is available (needed for config parsing)
if ! command -v python3 >/dev/null 2>&1; then
    fatal "Python3 is not installed. Please install it first: sudo apt-get install -y python3"
fi

# Change to installation directory
cd "$INSTALL_DIR" || fatal "Failed to change to $INSTALL_DIR"

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

log_step 2 6 "Ensuring permissions and prerequisites"

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
        fatal "Permission denied. Cannot write to .git directory. Please run: sudo chown -R knxohui:knxohui $INSTALL_DIR $BACKUP_DIR"
    fi
fi

if [[ -d "$BACKUP_DIR" ]] && [[ ! -w "$BACKUP_DIR" ]]; then
    log "Permission issue detected with backup directory."
    log "Attempting to fix backup directory ownership..."
    if sudo chown -R knxohui:knxohui "$BACKUP_DIR" 2>/dev/null; then
        log "Backup directory ownership fixed successfully."
    else
        fatal "Permission denied. Cannot write to backup directory: $BACKUP_DIR"
    fi
fi

# Mark the installation directory as safe for git operations
log "Ensuring git directory is marked as safe..."
sudo -u knxohui git config --global --add safe.directory "$INSTALL_DIR" 2>/dev/null || true

# If backup directory doesn't exist, create it with proper permissions
if [[ ! -d "$BACKUP_DIR" ]]; then
    log "Creating backup directory: $BACKUP_DIR"
    mkdir -p "$BACKUP_DIR" || fatal "Failed to create backup directory: $BACKUP_DIR"
fi

log_step 3 6 "Creating backup"

# Create backup of current installation
log "Creating backup of current installation..."
BACKUP_NAME="pre-update-$(date +%Y%m%d-%H%M%S).tar.gz"
BACKUP_PATH="$BACKUP_DIR/$BACKUP_NAME"

tar -czf "$BACKUP_PATH" \
    --exclude='.git' \
    --exclude='venv' \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='var' \
    . || log "WARNING: Backup creation failed, but continuing..."

if [[ -f "$BACKUP_PATH" ]]; then
    log "Backup created: $BACKUP_PATH"
else
    log "WARNING: Backup file not created"
fi

log_step 4 6 "Updating repository"

# Stash any local changes
log "Stashing local changes..."
if ! git -c safe.directory='*' stash; then
    log "WARNING: Git stash failed, continuing anyway..."
fi

# Verify git repository is properly configured
log "Verifying git repository configuration..."
if ! git -c safe.directory='*' rev-parse --git-dir > /dev/null 2>&1; then
    fatal "Not a valid git repository or access denied."
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
        fatal "Failed to fetch from GitHub after permission fix attempts"
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
    fatal "Git pull failed"
fi

log_step 5 6 "Updating dependencies and metadata"

# Update Python dependencies
log "Updating Python dependencies..."
if [[ -f "$INSTALL_DIR/venv/bin/pip" ]]; then
    "$INSTALL_DIR/venv/bin/pip" install --upgrade pip -q || log "WARNING: pip upgrade failed"
    if ! "$INSTALL_DIR/venv/bin/pip" install -r requirements.txt -q; then
        fatal "Failed to install dependencies"
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

log_step 6 6 "Restarting service and finalizing"

# Restart the service
log "Restarting $SERVICE_NAME..."
if ! sudo systemctl restart "$SERVICE_NAME"; then
    fatal "Failed to restart service"
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
log "Previous commit: $CURRENT_COMMIT"
log "New commit: $NEW_COMMIT"
log "Backup saved to: $BACKUP_PATH"
log "========================================="

exit 0
