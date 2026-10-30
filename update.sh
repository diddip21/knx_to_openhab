#!/usr/bin/env bash
# Self-update script for KNX to OpenHAB Generator
# This script is executed by the web UI when an update is requested

set -euo pipefail

# Configuration
# Resolve installation directory dynamically (can be overridden via INSTALL_DIR env var)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="${KNXOH_INSTALL_DIR:-${INSTALL_DIR:-$SCRIPT_DIR}}"
LOG_FILE="${LOG_FILE:-/var/log/knx_to_openhab_update.log}"
SERVICE_NAME="knxohui.service"

BACKUP_DIR="${KNXOH_BACKUP_DIR:-$(PYTHONPATH="$INSTALL_DIR" python3 -c \
    'from knxoh_paths import get_paths; print(get_paths().backup_dir)')}"

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

# This script pulls origin/main. Never let a test or feature checkout silently
# switch its code when the Web UI's update action is used.
CURRENT_BRANCH=$(git -c "safe.directory=$INSTALL_DIR" symbolic-ref --quiet --short HEAD 2>/dev/null || true)
if [[ "$CURRENT_BRANCH" != "main" ]]; then
    log "ERROR: Automatic updates are only available on main; current branch: ${CURRENT_BRANCH:-detached/unknown}."
    exit 1
fi

# The previous release granted passwordless root Git access. A Web UI update
# cannot safely replace that policy itself, so require the one-time admin
# migration before allowing another update to proceed.
if ! SUDO_POLICY=$(sudo -n -l 2>/dev/null); then
    log "ERROR: Cannot verify the service user's sudoers policy. Run 'sudo bash $INSTALL_DIR/installer/migrate_sudoers.sh' as an administrator, then retry."
    exit 1
fi
if printf '%s\n' "$SUDO_POLICY" | grep -Eq '(/usr/bin/git|/bin/git)[[:space:]]+\\*|NOPASSWD:[[:space:]]+ALL'; then
    log "ERROR: The legacy broad sudoers policy is still installed. Run 'sudo bash $INSTALL_DIR/installer/migrate_sudoers.sh' as an administrator before updating again."
    exit 1
fi

# Refuse an in-place update until credentials live in the external config tree.
# An older checkout may still keep its default or plaintext password in tracked
# files, so fetching first could replace the code before credentials are migrated.
PATHS_FILE="${KNXOH_PATHS_FILE:-/etc/knx_to_openhab/paths.env}"
if [[ ! -x "$INSTALL_DIR/venv/bin/python" ]]; then
    log "ERROR: The installed Python environment is missing; credential migration cannot be verified."
    log "Recovery: run 'sudo bash $INSTALL_DIR/installer/setup.sh' from an interactive SSH terminal, then retry."
    exit 1
fi
if ! CREDENTIAL_CHECK=$(KNXOH_INSTALL_DIR="$INSTALL_DIR" KNXOH_PATHS_FILE="$PATHS_FILE" \
    PYTHONPATH="$INSTALL_DIR" "$INSTALL_DIR/venv/bin/python" - "$PATHS_FILE" <<'PY' 2>&1
import base64
import binascii
import json
import sys
from pathlib import Path

from knxoh_paths import get_paths
from web_ui.backend.auth import is_password_hash

paths_file = Path(sys.argv[1])
if not paths_file.is_file():
    raise SystemExit(f"installer paths file is missing: {paths_file}")
paths = get_paths()
if (
    paths.secrets_file is None
    or paths.config_dir == paths.install_dir
    or paths.install_dir in paths.config_dir.parents
):
    raise SystemExit("external Web UI configuration is not installed")
if not paths.web_config_file.is_file() or not paths.secrets_file.is_file():
    raise SystemExit("external Web UI config.json or secrets.env is missing")
try:
    config = json.loads(paths.web_config_file.read_text(encoding="utf-8"))
except (OSError, json.JSONDecodeError) as error:
    raise SystemExit(f"cannot read external Web UI config: {error}") from error
auth = config.get("auth", {}) if isinstance(config, dict) else None
if not isinstance(auth, dict):
    raise SystemExit("external Web UI auth configuration is invalid")
if auth.get("enabled", True):
    encoded_hash = None
    for line in paths.secrets_file.read_text(encoding="utf-8").splitlines():
        name, separator, value = line.partition("=")
        if separator and name == "KNXOH_UI_PASSWORD_HASH_B64":
            encoded_hash = value.strip()
    try:
        password_hash = base64.b64decode(encoded_hash, validate=True).decode("utf-8")
    except (TypeError, binascii.Error, UnicodeDecodeError) as error:
        raise SystemExit("a valid external Argon2id password hash is required") from error
    if not is_password_hash(password_hash):
        raise SystemExit("a valid external Argon2id password hash is required")
PY
); then
    log "ERROR: Credential migration is incomplete: $CREDENTIAL_CHECK"
    log "Recovery: run 'sudo bash $INSTALL_DIR/installer/setup.sh' from an interactive SSH terminal, then retry."
    exit 1
fi
log "External Web UI configuration and password hash are ready."

# The updater runs as the service user. It must not elevate to repair ownership.
if [[ ! -w ".git" ]]; then
    log "ERROR: The service user cannot write to $INSTALL_DIR/.git. Run fix_permissions.sh as an administrator."
    exit 1
fi

if [[ -d "$BACKUP_DIR" ]] && [[ ! -w "$BACKUP_DIR" ]]; then
    log "ERROR: The service user cannot write to backup directory $BACKUP_DIR. Run fix_permissions.sh as an administrator."
    exit 1
fi

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
if ! git -c "safe.directory=$INSTALL_DIR" stash; then
    log "WARNING: Git stash failed, continuing anyway..."
fi

# Verify git repository is properly configured
log "Verifying git repository configuration..."
if ! git -c "safe.directory=$INSTALL_DIR" rev-parse --git-dir > /dev/null 2>&1; then
    log "ERROR: Not a valid git repository or access denied."
    log "Please verify the installation directory and permissions."
    exit 1
fi

# Fetch latest changes from GitHub
log "Fetching latest changes from GitHub..."
if ! git -c "safe.directory=$INSTALL_DIR" fetch origin; then
    log "ERROR: Failed to fetch from GitHub. Check network access and repository permissions."
    exit 1
fi

# Get current and remote commit hashes
CURRENT_COMMIT=$(git -c "safe.directory=$INSTALL_DIR" rev-parse HEAD)
REMOTE_COMMIT=$(git -c "safe.directory=$INSTALL_DIR" rev-parse origin/main)

log "Current commit: $CURRENT_COMMIT"
log "Remote commit: $REMOTE_COMMIT"

if [[ "$CURRENT_COMMIT" == "$REMOTE_COMMIT" ]]; then
    log "Already up to date!"
    exit 0
fi

# Pull latest changes
log "Pulling latest changes..."
if ! git -c "safe.directory=$INSTALL_DIR" pull origin main; then
    log "ERROR: Git pull failed"
    log "Attempting to restore from backup..."
    git -c "safe.directory=$INSTALL_DIR" reset --hard "$CURRENT_COMMIT"
    exit 1
fi

# Update Python dependencies
log "Updating Python dependencies..."
if [[ -f "$INSTALL_DIR/venv/bin/pip" ]]; then
    "$INSTALL_DIR/venv/bin/pip" install --upgrade pip -q || log "WARNING: pip upgrade failed"
    if ! "$INSTALL_DIR/venv/bin/pip" install -r requirements.txt -q; then
        log "ERROR: Failed to install dependencies"
        log "Attempting to restore from backup..."
        git -c "safe.directory=$INSTALL_DIR" reset --hard "$CURRENT_COMMIT"
        exit 1
    fi
else
    log "WARNING: Virtual environment not found, skipping dependency update"
fi

# Update version.json with new commit hash
log "Updating version.json..."
NEW_COMMIT=$(git -c "safe.directory=$INSTALL_DIR" rev-parse HEAD)
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

wait_for_service_active() {
    local attempt
    for attempt in {1..15}; do
        if sudo systemctl is-active "$SERVICE_NAME" > /dev/null; then
            return 0
        fi
        sleep 1
    done
    return 1
}

restore_previous_release() {
    log "Restoring previous application commit $CURRENT_COMMIT..."
    if ! git -c "safe.directory=$INSTALL_DIR" reset --hard "$CURRENT_COMMIT"; then
        log "ERROR: Could not restore the previous application files."
        return 1
    fi

    if [[ -x "$INSTALL_DIR/venv/bin/pip" ]]; then
        if ! "$INSTALL_DIR/venv/bin/pip" install -r "$INSTALL_DIR/requirements.txt" -q; then
            log "WARNING: Could not fully restore the previous Python dependencies."
        fi
    fi

    if ! sudo systemctl restart "$SERVICE_NAME"; then
        log "ERROR: The previous version could not be restarted."
        return 1
    fi
    if wait_for_service_active; then
        log "Previous version restored and service is active."
        return 0
    fi
    log "ERROR: The previous version is restored, but the service is still inactive."
    return 1
}

log "Restarting $SERVICE_NAME..."
if ! sudo systemctl restart "$SERVICE_NAME"; then
    log "ERROR: Failed to restart the updated service."
    restore_previous_release || log "ERROR: Automatic recovery failed. Check: sudo systemctl status $SERVICE_NAME"
    exit 1
fi

if ! wait_for_service_active; then
    log "ERROR: The updated service did not become active."
    restore_previous_release || log "ERROR: Automatic recovery failed. Check: sudo systemctl status $SERVICE_NAME"
    exit 1
fi

log "Service restarted successfully"
log "========================================="
log "Update completed successfully!"
log "New commit: $NEW_COMMIT"
log "Backup saved to: $BACKUP_PATH"
log "========================================="

exit 0
