#!/usr/bin/env bash
# Uninstaller for KNX to OpenHAB Generator
# Usage: curl -sSL https://raw.githubusercontent.com/diddip21/knx_to_openhab/main/uninstall.sh | bash

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

DRY_RUN=0
INSTALL_DIR="${INSTALL_DIR:-/opt/knx_to_openhab}"

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
log_warning() { echo -e "${YELLOW}[WARNING]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

usage() {
    echo "Usage: $0 [--dry-run]"
}

for arg in "$@"; do
    case "$arg" in
        --dry-run)
            DRY_RUN=1
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            log_error "Unknown argument: $arg"
            usage
            exit 1
            ;;
    esac
done

if [[ $EUID -eq 0 ]]; then
    log_error "This script should NOT be run as root. Please run as a regular user with sudo privileges."
    exit 1
fi

if [[ ! -d "$INSTALL_DIR" ]]; then
    log_warning "No installation found at $INSTALL_DIR. Nothing to uninstall."
    exit 0
fi

log_info "Starting uninstallation..."

# Read config to get the actual backup directory path
if command -v python3 >/dev/null 2>&1 && [ -f "$INSTALL_DIR/web_ui/backend/config.json" ]; then
    BACKUPS_DIR=$(python3 - <<PY
import json
cfg=json.load(open('$INSTALL_DIR/web_ui/backend/config.json'))
print(cfg.get('backups_dir','/var/backups/knx_to_openhab'))
PY
)
    JOBS_DIR=$(python3 - <<PY
import json
cfg=json.load(open('$INSTALL_DIR/web_ui/backend/config.json'))
print(cfg.get('jobs_dir','/var/lib/knx_to_openhab'))
PY
)
elif [[ ! -f "$INSTALL_DIR/web_ui/backend/config.json" ]]; then
    BACKUPS_DIR="/var/backups/knx_to_openhab"
    JOBS_DIR="/var/lib/knx_to_openhab"
else
    log_warning "Python3 not available; using default backup and jobs directories."
    BACKUPS_DIR="/var/backups/knx_to_openhab"
    JOBS_DIR="/var/lib/knx_to_openhab"
fi

# If paths are relative, make them absolute for installation directory
if [[ "$BACKUPS_DIR" != /* ]]; then
    BACKUPS_DIR="$INSTALL_DIR/$BACKUPS_DIR"
fi

if [[ "$JOBS_DIR" != /* ]]; then
    JOBS_DIR="$INSTALL_DIR/$JOBS_DIR"
fi

DELETE_PATHS=(
    "$INSTALL_DIR"
    "$JOBS_DIR"
    "$BACKUPS_DIR"
    "/etc/systemd/system/knxohui.service"
    "/etc/systemd/system/knxohui-backup-cleanup.service"
    "/etc/systemd/system/knxohui-backup-cleanup.timer"
    "/etc/sudoers.d/knxohui"
)

log_info "The following paths will be removed:"
for path in "${DELETE_PATHS[@]}"; do
    echo "  - $path"
done

if [[ "$DRY_RUN" -eq 1 ]]; then
    log_info "Dry-run enabled. No changes made."
    exit 0
fi

echo -ne "Type 'yes' to confirm uninstallation: " >&2
read -r CONFIRM < /dev/tty
if [[ "$CONFIRM" != "yes" ]]; then
    log_info "Uninstallation cancelled."
    exit 0
fi

# 1. Stop and disable services
log_info "Stopping services..."
sudo systemctl stop knxohui.service || true
sudo systemctl stop knxohui-backup-cleanup.timer || true
sudo systemctl disable knxohui.service || true
sudo systemctl disable knxohui-backup-cleanup.timer || true

# 2. Remove systemd units
log_info "Removing systemd units..."
sudo rm -f /etc/systemd/system/knxohui.service
sudo rm -f /etc/systemd/system/knxohui-backup-cleanup.service
sudo rm -f /etc/systemd/system/knxohui-backup-cleanup.timer
sudo systemctl daemon-reload

# 3. Remove sudoers file
log_info "Removing sudoers configuration..."
sudo rm -f /etc/sudoers.d/knxohui

# 4. Remove directories
log_info "Removing directories..."
sudo rm -rf "$INSTALL_DIR"
sudo rm -rf "$JOBS_DIR"
sudo rm -rf "$BACKUPS_DIR"

# 5. Remove user
log_info "Removing service user..."
if id "knxohui" &>/dev/null; then
    sudo userdel knxohui || log_warning "Could not delete user knxohui (might be in use)"
else
    log_info "User knxohui does not exist"
fi

log_success "Uninstallation complete. All components have been removed."
log_info "Manual cleanup may still be required:"
log_info "  - Remove any remaining backups or logs"
log_info "  - Check /etc/openhab permissions if modified"
