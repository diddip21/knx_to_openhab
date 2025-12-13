#!/usr/bin/env bash
# Uninstaller for KNX to OpenHAB Generator
# Usage: curl -sSL https://raw.githubusercontent.com/diddip21/knx_to_openhab/main/uninstall.sh | bash

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
log_warning() { echo -e "${YELLOW}[WARNING]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

if [[ $EUID -eq 0 ]]; then
    log_error "This script should NOT be run as root. Please run as a regular user with sudo privileges."
    exit 1
fi

log_info "Starting uninstallation..."

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
sudo rm -rf /opt/knx_to_openhab
sudo rm -rf /var/lib/knx_to_openhab
sudo rm -rf /var/backups/knx_to_openhab

# 5. Remove user
log_info "Removing service user..."
if id "knxohui" &>/dev/null; then
    sudo userdel knxohui || log_warning "Could not delete user knxohui (might be in use)"
else
    log_info "User knxohui does not exist"
fi

log_success "Uninstallation complete. All components have been removed."
