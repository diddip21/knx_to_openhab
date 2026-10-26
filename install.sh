#!/usr/bin/env bash
# One-Command Installer for KNX to OpenHAB Generator
# Usage: curl -sSL https://raw.githubusercontent.com/diddip21/knx_to_openhab/main/install.sh | bash

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
REPO_URL="https://github.com/diddip21/knx_to_openhab.git"
PATHS_FILE="/etc/knx_to_openhab/paths.env"
read_saved_install_dir() {
    python3 - "$PATHS_FILE" <<'PY'
import shlex
import sys
try:
    lines = open(sys.argv[1], encoding="utf-8").read().splitlines()
except FileNotFoundError:
    print("/opt/knx_to_openhab")
    raise SystemExit(0)
for line in lines:
    if line.startswith("KNXOH_INSTALL_DIR="):
        value = shlex.split(line.split("=", 1)[1], posix=True)
        if len(value) == 1:
            print(value[0])
            raise SystemExit(0)
print("/opt/knx_to_openhab")
PY
}
INSTALL_DIR="${KNXOH_INSTALL_DIR:-$(read_saved_install_dir)}"
BRANCH="main"

# Helper functions
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

check_root() {
    if [[ $EUID -eq 0 ]]; then
        if [[ "${ALLOW_ROOT:-0}" != "1" ]]; then
            log_error "This script is running as root. Set ALLOW_ROOT=1 if you really want to allow this."
            exit 1
        fi
        log_warning "Running installer as root because ALLOW_ROOT=1; proceeding with caution."
    fi
}

check_os() {
    if [[ ! -f /etc/os-release ]]; then
        log_error "Cannot detect OS. /etc/os-release not found."
        exit 1
    fi
    
    . /etc/os-release
    
    if [[ "$ID" != "debian" ]] && [[ "$ID_LIKE" != *"debian"* ]]; then
        log_warning "This installer is designed for Debian-based systems (DietPi, Raspbian, Ubuntu)."
        log_warning "Detected OS: $PRETTY_NAME"
        echo -ne "Continue anyway? (y/N) " >&2
        read -n 1 -r < /dev/tty
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            exit 1
        fi
    else
        log_info "Detected OS: $PRETTY_NAME"
    fi
}

check_sudo() {
    if ! sudo -n true 2>/dev/null; then
        log_info "Testing sudo access..."
        sudo -v || {
            log_error "This script requires sudo privileges. Please ensure your user has sudo access."
            exit 1
        }
    fi
    log_success "Sudo access confirmed"
}

install_dependencies() {
    log_info "Installing system dependencies..."
    
    sudo apt-get update -qq
    
    local packages=(
        "git"
        "python3"
        "python3-venv"
        "python3-pip"
        "rsync"
        "curl"
    )
    
    for pkg in "${packages[@]}"; do
        if ! dpkg -l | grep -q "^ii  $pkg "; then
            log_info "Installing $pkg..."
            sudo apt-get install -y -qq "$pkg" || {
                log_error "Failed to install $pkg"
                exit 1
            }
        else
            log_info "$pkg is already installed"
        fi
    done
    
    log_success "All dependencies installed"
}

clone_repository() {
    log_info "Cloning repository from $REPO_URL..."
    
    if [[ -d "$INSTALL_DIR" ]]; then
        log_warning "Installation directory $INSTALL_DIR already exists"
        echo -ne "Update or repair it in place? (Y/n) " >&2
        read -n 1 -r < /dev/tty
        echo
        if [[ $REPLY =~ ^[Nn]$ ]]; then
            log_info "Leaving the existing installation unchanged"
            exit 0
        fi
        if [[ ! -d "$INSTALL_DIR/.git" ]]; then
            log_error "Existing installation is not a Git checkout; it was left untouched"
            exit 1
        fi
        log_info "Updating existing installation as the service user..."
        if id -u knxohui >/dev/null 2>&1; then
            sudo -u knxohui git -C "$INSTALL_DIR" pull --ff-only origin "$BRANCH" || {
                log_error "Failed to update repository"
                exit 1
            }
        else
            git -C "$INSTALL_DIR" pull --ff-only origin "$BRANCH" || {
                log_error "Failed to update repository"
                exit 1
            }
        fi
        log_success "Repository updated"
        return 0
    fi
    
    TEMP_DIR=$(mktemp -d)
    if ! git clone --branch "$BRANCH" "$REPO_URL" "$TEMP_DIR/repository"; then
        rm -rf "$TEMP_DIR"
        log_error "Failed to clone repository"
        exit 1
    fi
    sudo install -d -m 0755 "$INSTALL_DIR"
    sudo rsync -a "$TEMP_DIR/repository/" "$INSTALL_DIR/"
    rm -rf "$TEMP_DIR"
    
    log_success "Repository cloned successfully"
}

run_setup_script() {
    log_info "Running setup script..."
    
    cd "$INSTALL_DIR"
    
    if [[ ! -f "installer/setup.sh" ]]; then
        log_error "Setup script not found at installer/setup.sh"
        exit 1
    fi
    
    chmod +x installer/setup.sh installer/backup_cleanup.sh
    
    bash installer/setup.sh || {
        log_error "Setup script failed"
        exit 1
    }
    
    log_success "Setup completed successfully"
}

display_completion() {
    local ip_address=$(hostname -I | awk '{print $1}')
    
    echo ""
    echo -e "${GREEN}╔════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║                                                            ║${NC}"
    echo -e "${GREEN}║  ✓ KNX to OpenHAB Generator installed successfully!       ║${NC}"
    echo -e "${GREEN}║                                                            ║${NC}"
    echo -e "${GREEN}╚════════════════════════════════════════════════════════════╝${NC}"
    echo ""
    echo -e "${BLUE}Installation Details:${NC}"
    echo -e "  • Installation directory: ${YELLOW}$INSTALL_DIR${NC}"
    echo -e "  • Service name: ${YELLOW}knxohui.service${NC}"
    echo -e "  • Web UI URL: ${YELLOW}http://$ip_address:8085${NC}"
    echo ""
    echo -e "${BLUE}Web UI Credentials:${NC}"
    echo -e "  • Username: ${YELLOW}admin${NC} (unless changed in the external config)"
    echo -e "  • Password: ${YELLOW}the password set during installation${NC}"
    echo ""
    echo -e "${BLUE}Password hashes and Web UI settings are stored under /etc/knx_to_openhab.${NC}"
    echo ""
    echo -e "${BLUE}Useful Commands:${NC}"
    echo -e "  • Check status: ${YELLOW}sudo systemctl status knxohui.service${NC}"
    echo -e "  • View logs: ${YELLOW}sudo journalctl -u knxohui.service -f${NC}"
    echo -e "  • Restart service: ${YELLOW}sudo systemctl restart knxohui.service${NC}"
    echo ""
    echo -e "${GREEN}Happy automating! 🏠${NC}"
    echo ""
}

# Main installation flow
main() {
    echo ""
    echo -e "${BLUE}╔════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${BLUE}║                                                            ║${NC}"
    echo -e "${BLUE}║     KNX to OpenHAB Generator - One-Command Installer       ║${NC}"
    echo -e "${BLUE}║                                                            ║${NC}"
    echo -e "${BLUE}╚════════════════════════════════════════════════════════════╝${NC}"
    echo ""
    
    check_root
    check_os
    check_sudo
    install_dependencies
    clone_repository
    run_setup_script
    display_completion
}

# Run main function
main "$@"
