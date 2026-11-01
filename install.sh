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
read_saved_config_dir() {
    python3 - "$PATHS_FILE" <<'PY'
import shlex
import sys
try:
    lines = open(sys.argv[1], encoding="utf-8").read().splitlines()
except FileNotFoundError:
    print("/etc/knx_to_openhab")
    raise SystemExit(0)
for line in lines:
    if line.startswith("KNXOH_CONFIG_DIR="):
        value = shlex.split(line.split("=", 1)[1], posix=True)
        if len(value) == 1:
            print(value[0])
            raise SystemExit(0)
print("/etc/knx_to_openhab")
PY
}
INSTALL_DIR="${KNXOH_INSTALL_DIR:-$(read_saved_install_dir)}"
CONFIG_DIR="${KNXOH_CONFIG_DIR:-$(read_saved_config_dir)}"
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

usage() {
    cat <<'USAGE'
Usage: bash install.sh [--install | --update | --repair | --cancel]

Modes:
  --install  Install into a new directory (the default on first install)
  --update   Pull the latest source into an existing Git checkout, then run setup
  --repair   Run setup for an existing installation without pulling source
  --cancel   Exit without changing the installation
  --help     Show this help
USAGE
}

INSTALL_MODE=""

parse_install_mode() {
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --install|--update|--repair|--cancel)
                if [[ -n "$INSTALL_MODE" ]]; then
                    log_error "Choose exactly one installer mode."
                    usage >&2
                    exit 2
                fi
                INSTALL_MODE="${1#--}"
                ;;
            --help|-h)
                usage
                exit 0
                ;;
            *)
                log_error "Unknown option: $1"
                usage >&2
                exit 2
                ;;
        esac
        shift
    done
}

select_install_mode() {
    if [[ "$INSTALL_MODE" == "cancel" ]]; then
        log_info "Installation cancelled; no system or installation changes were made."
        exit 0
    fi

    if [[ -L "$INSTALL_DIR" ]]; then
        log_error "Installation path is a symbolic link: $INSTALL_DIR"
        exit 2
    fi
    if [[ -e "$INSTALL_DIR" && ! -d "$INSTALL_DIR" ]]; then
        log_error "Installation path exists but is not a directory: $INSTALL_DIR"
        exit 2
    fi

    if [[ -d "$INSTALL_DIR" ]]; then
        if [[ -z "$INSTALL_MODE" ]]; then
            local choice
            local tty_fd
            if ! { exec {tty_fd}<>/dev/tty; } 2>/dev/null; then
                log_error "An installation already exists at $INSTALL_DIR."
                log_error "Choose --update, --repair or --cancel. No changes were made."
                exit 2
            fi

            echo "" >&2
            echo "An installation already exists at $INSTALL_DIR." >&2
            echo "  [u] Update source and run setup" >&2
            echo "  [r] Repair by running setup without updating source" >&2
            echo "  [c] Cancel (default)" >&2
            if ! read -r -n 1 -u "$tty_fd" -p "Select u/r/c: " choice; then
                exec {tty_fd}>&-
                echo "" >&2
                log_error "Could not read installer choice. No changes were made."
                exit 2
            fi
            exec {tty_fd}>&-
            echo "" >&2
            case "$choice" in
                u|U) INSTALL_MODE="update" ;;
                r|R) INSTALL_MODE="repair" ;;
                ""|c|C) INSTALL_MODE="cancel" ;;
                *)
                    log_error "Invalid installer choice. No changes were made."
                    exit 2
                    ;;
            esac
            if [[ "$INSTALL_MODE" == "cancel" ]]; then
                log_info "Installation cancelled; no system or installation changes were made."
                exit 0
            fi
        fi

        case "$INSTALL_MODE" in
            install)
                log_error "An installation already exists at $INSTALL_DIR."
                log_error "Use --update, --repair or --cancel; existing files were left untouched."
                exit 2
                ;;
            update)
                if [[ ! -e "$INSTALL_DIR/.git" ]]; then
                    log_error "Cannot update $INSTALL_DIR: it is not a Git checkout."
                    exit 2
                fi
                ;;
            repair)
                if [[ ! -f "$INSTALL_DIR/installer/setup.sh" ]]; then
                    log_error "Cannot repair $INSTALL_DIR: installer/setup.sh is missing."
                    exit 2
                fi
                ;;
            *)
                log_error "Invalid installer mode: $INSTALL_MODE"
                exit 2
                ;;
        esac
    else
        case "$INSTALL_MODE" in
            "")
                INSTALL_MODE="install"
                ;;
            install)
                ;;
            update|repair)
                log_error "No existing installation found at $INSTALL_DIR."
                exit 2
                ;;
            *)
                log_error "Invalid installer mode: $INSTALL_MODE"
                exit 2
                ;;
        esac
    fi
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
    if [[ "$INSTALL_MODE" == "update" ]]; then
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

    if [[ "$INSTALL_MODE" == "repair" ]]; then
        log_info "Repairing the existing installation without pulling source..."
        return 0
    fi

    log_info "Cloning repository from $REPO_URL..."
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
    local ip_addresses=$(hostname -I)
    local ip_address="${ip_addresses%% *}"
    local ui_settings
    ui_settings=$(sudo python3 "$INSTALL_DIR/installer/web_ui_endpoint.py" \
        --config "$CONFIG_DIR/config.json" --lan-ip "$ip_addresses")
    local -a ui_values=()
    mapfile -t ui_values <<<"$ui_settings"
    local binding_mode="${ui_values[0]:-loopback}"
    local ui_host="${ui_values[1]:-127.0.0.1}"
    local port="${ui_values[2]:-8085}"
    
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
    echo -e "  • Web UI URL: ${YELLOW}http://$ui_host:$port${NC}"
    if [[ "$binding_mode" == "loopback" ]]; then
        local device_host="${ip_address:-your-device-ip}"
        echo -e "  • Local-only listener. For remote access, run: ${YELLOW}ssh -L $port:$ui_host:$port <user>@$device_host${NC}"
        echo -e "    Then open ${YELLOW}http://$ui_host:$port${NC} in your browser."
    fi
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
    select_install_mode

    echo ""
    echo -e "${BLUE}╔════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${BLUE}║                                                            ║${NC}"
    echo -e "${BLUE}║     KNX to OpenHAB Generator - One-Command Installer       ║${NC}"
    echo -e "${BLUE}║                                                            ║${NC}"
    echo -e "${BLUE}╚════════════════════════════════════════════════════════════╝${NC}"
    echo ""

    log_info "Selected installer mode: $INSTALL_MODE"
    check_root
    check_os
    check_sudo
    install_dependencies
    clone_repository
    run_setup_script
    display_completion
}

# Parse options before checks that can access the system.
parse_install_mode "$@"

# Run main function
main
