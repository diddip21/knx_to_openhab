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
INSTALL_DIR="/opt/knx_to_openhab"
BRANCH="main"
MIN_DISK_MB=100

# State
EXISTING_INSTALL=0
CREATED_INSTALL_DIR=0

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

log_step() {
    local step="$1"
    local total="$2"
    local message="$3"
    echo -e "${BLUE}[${step}/${total}]${NC} $message"
}

on_error() {
    log_error "Installation failed."
    if [[ "$CREATED_INSTALL_DIR" -eq 1 ]]; then
        log_warning "Cleaning up partially created installation at $INSTALL_DIR"
        sudo rm -rf "$INSTALL_DIR" || true
    fi
    log_info "You can re-run the installer after fixing the issue."
}
trap on_error ERR

check_root() {
    if [[ $EUID -eq 0 ]]; then
        log_error "This script should NOT be run as root. Please run as a regular user with sudo privileges."
        exit 1
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

check_disk_space() {
    local target_dir="$INSTALL_DIR"
    local mount_point
    mount_point=$(df -P "$target_dir" 2>/dev/null | awk 'NR==2 {print $6}')
    if [[ -z "$mount_point" ]]; then
        mount_point="/"
    fi
    local available_mb
    available_mb=$(df -Pm "$mount_point" | awk 'NR==2 {print $4}')
    if [[ "$available_mb" -lt "$MIN_DISK_MB" ]]; then
        log_error "Not enough disk space. Required: ${MIN_DISK_MB}MB, Available: ${available_mb}MB on $mount_point"
        exit 1
    fi
    log_success "Disk space check passed (${available_mb}MB available)"
}

check_python_version() {
    if ! command -v python3 >/dev/null 2>&1; then
        log_error "Python3 is not installed. Please install it first: sudo apt-get install -y python3"
        exit 1
    fi

    local py_ver
    py_ver=$(python3 - <<'PY'
import sys
print(f"{sys.version_info.major}.{sys.version_info.minor}")
PY
)
    if [[ -z "$py_ver" ]]; then
        log_error "Unable to determine Python version."
        exit 1
    fi
    log_success "Python version detected: $py_ver"
}

check_python_modules() {
    if ! python3 - <<'PY' >/dev/null 2>&1
import venv, pip
PY
    then
        log_warning "Python modules venv/pip not available. Installer will attempt to install python3-venv and python3-pip."
    else
        log_success "Python venv and pip are available"
    fi
}

check_dependencies() {
    local missing=()
    for cmd in git rsync curl; do
        if ! command -v "$cmd" >/dev/null 2>&1; then
            missing+=("$cmd")
        fi
    done

    if [[ ${#missing[@]} -gt 0 ]]; then
        log_warning "Missing dependencies: ${missing[*]}"
        log_warning "They will be installed automatically (requires sudo)."
    else
        log_success "All required system commands are available"
    fi
}

preflight_checks() {
    log_step 1 6 "Running pre-flight checks..."
    check_root
    check_os
    check_sudo
    check_disk_space
    check_python_version
    check_python_modules
    check_dependencies
}

install_dependencies() {
    log_step 2 6 "Installing system dependencies..."

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

handle_existing_install() {
    if [[ -d "$INSTALL_DIR" ]]; then
        EXISTING_INSTALL=1
        log_warning "Installation directory $INSTALL_DIR already exists."
        echo "Choose an option:"
        echo "  [U]pdate existing installation"
        echo "  [R]epair (re-run setup)"
        echo "  [A]bort"
        echo -ne "Your choice (U/R/A): " >&2
        read -n 1 -r < /dev/tty
        echo
        case "$REPLY" in
            [Uu])
                log_info "Running update..."
                if [[ -x "$INSTALL_DIR/update.sh" ]]; then
                    bash "$INSTALL_DIR/update.sh"
                else
                    log_error "update.sh not found in $INSTALL_DIR"
                    exit 1
                fi
                display_completion
                exit 0
                ;;
            [Rr])
                log_info "Repairing installation..."
                run_setup_script
                display_completion
                exit 0
                ;;
            *)
                log_info "Aborting per user request."
                exit 0
                ;;
        esac
    fi
}

clone_repository() {
    log_step 3 6 "Cloning repository from $REPO_URL..."

    sudo mkdir -p "$INSTALL_DIR"
    sudo chown "$USER":"$USER" "$INSTALL_DIR"
    CREATED_INSTALL_DIR=1

    git clone --branch "$BRANCH" "$REPO_URL" "$INSTALL_DIR" || {
        log_error "Failed to clone repository"
        exit 1
    }

    log_success "Repository cloned successfully"
}

run_setup_script() {
    log_step 4 6 "Running setup script..."

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
    local ip_address
    ip_address=$(hostname -I | awk '{print $1}')

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
    echo -e "${BLUE}Default Credentials:${NC}"
    echo -e "  • Username: ${YELLOW}admin${NC}"
    echo -e "  • Password: ${YELLOW}logihome${NC}"
    echo ""
    echo -e "${RED}⚠ IMPORTANT: Change the default password!${NC}"
    echo -e "  Edit: ${YELLOW}$INSTALL_DIR/web_ui/backend/config.json${NC}"
    echo -e "  Then run: ${YELLOW}sudo systemctl restart knxohui.service${NC}"
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

    preflight_checks
    handle_existing_install
    install_dependencies
    clone_repository
    run_setup_script
    log_step 5 6 "Finalizing installation..."
    display_completion
    log_step 6 6 "Done."
}

# Run main function
main "$@"
