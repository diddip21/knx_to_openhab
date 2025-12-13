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
        echo -ne "Remove and reinstall? (y/N) " >&2
        read -n 1 -r < /dev/tty
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            log_info "Removing existing installation..."
            sudo rm -rf "$INSTALL_DIR"
        else
            log_info "Updating existing installation..."
            cd "$INSTALL_DIR"
            sudo -u "$USER" git pull origin "$BRANCH" || {
                log_error "Failed to update repository"
                exit 1
            }
            log_success "Repository updated"
            return 0
        fi
    fi
    
    sudo mkdir -p "$INSTALL_DIR"
    sudo chown "$USER":"$USER" "$INSTALL_DIR"
    
    git clone --branch "$BRANCH" "$REPO_URL" "$INSTALL_DIR" || {
        log_error "Failed to clone repository"
        exit 1
    }
    
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
    echo -e "  • Service name: ${YELLOW}knxui.service${NC}"
    echo -e "  • Web UI URL: ${YELLOW}http://$ip_address:8080${NC}"
    echo ""
    echo -e "${BLUE}Default Credentials:${NC}"
    echo -e "  • Username: ${YELLOW}admin${NC}"
    echo -e "  • Password: ${YELLOW}changeme${NC}"
    echo ""
    echo -e "${RED}⚠ IMPORTANT: Change the default password!${NC}"
    echo -e "  Edit: ${YELLOW}$INSTALL_DIR/web_ui/backend/config.json${NC}"
    echo -e "  Then run: ${YELLOW}sudo systemctl restart knxui.service${NC}"
    echo ""
    echo -e "${BLUE}Useful Commands:${NC}"
    echo -e "  • Check status: ${YELLOW}sudo systemctl status knxui.service${NC}"
    echo -e "  • View logs: ${YELLOW}sudo journalctl -u knxui.service -f${NC}"
    echo -e "  • Restart service: ${YELLOW}sudo systemctl restart knxui.service${NC}"
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
