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
PATHS_FILE="${KNXOH_PATHS_FILE:-/etc/knx_to_openhab/paths.env}"
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
INSTALL_DIR="${KNXOH_INSTALL_DIR:-}"
CONFIG_DIR="${KNXOH_CONFIG_DIR:-}"
SETUP_APP_DIR=""
REQUESTED_VERSION=""
RELEASE_VERSION=""
RELEASE_TAG=""

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

is_valid_semver() {
    local pattern='^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(-([0-9A-Za-z-]+(\.[0-9A-Za-z-]+)*))?(\+([0-9A-Za-z-]+(\.[0-9A-Za-z-]+)*))?$'
    local prerelease identifier
    local -a identifiers

    if [[ ! "$1" =~ $pattern ]]; then
        return 1
    fi
    prerelease="${BASH_REMATCH[5]:-}"
    IFS=. read -r -a identifiers <<<"$prerelease"
    for identifier in "${identifiers[@]}"; do
        if [[ "$identifier" =~ ^0[0-9]+$ ]]; then
            return 1
        fi
    done
}

is_version_older() {
    python3 - "$1" "$2" <<'PY'
import re
import sys

pattern = re.compile(
    r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)

def parse(version):
    match = pattern.fullmatch(version)
    if not match:
        return None
    prerelease = match.group(4)
    identifiers = tuple(prerelease.split(".")) if prerelease else None
    if identifiers and any(
        value.isdigit() and len(value) > 1 and value.startswith("0")
        for value in identifiers
    ):
        return None
    return tuple(map(int, match.group(1, 2, 3))), identifiers

candidate = parse(sys.argv[1])
installed = parse(sys.argv[2])
if candidate is None or installed is None:
    raise SystemExit(1)

candidate_core, candidate_pre = candidate
installed_core, installed_pre = installed
if candidate_core != installed_core:
    older = candidate_core < installed_core
elif candidate_pre is None or installed_pre is None:
    older = candidate_pre is not None and installed_pre is None
else:
    older = False
    for candidate_id, installed_id in zip(candidate_pre, installed_pre):
        if candidate_id == installed_id:
            continue
        candidate_numeric = candidate_id.isdigit()
        installed_numeric = installed_id.isdigit()
        if candidate_numeric and installed_numeric:
            older = int(candidate_id) < int(installed_id)
        elif candidate_numeric != installed_numeric:
            older = candidate_numeric
        else:
            older = candidate_id < installed_id
        break
    else:
        older = len(candidate_pre) < len(installed_pre)

raise SystemExit(0 if older else 1)
PY
}

resolve_release_version() {
    local requested_version="${1:-}"
    local endpoint="/releases/latest"
    if [[ -n "$requested_version" ]]; then
        endpoint="/releases/tags/v$requested_version"
    fi

    local response
    if ! response="$(curl --fail --silent --show-error --location --retry 2 \
        -H "Accept: application/vnd.github+json" \
        -H "X-GitHub-Api-Version: 2022-11-28" \
        "https://api.github.com/repos/diddip21/knx_to_openhab$endpoint" 2>/dev/null)"; then
        if [[ -n "$requested_version" ]]; then
            echo "Could not retrieve the published release v$requested_version." >&2
        else
            echo "Could not retrieve the latest stable GitHub release." >&2
        fi
        return 1
    fi

    printf '%s' "$response" | python3 -c '
import json
import re
import sys

def fail(message):
    print(f"Release selection failed: {message}", file=sys.stderr)
    raise SystemExit(1)

pattern = re.compile(
    r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
    r"(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$"
)
try:
    release = json.load(sys.stdin)
except (json.JSONDecodeError, UnicodeDecodeError) as error:
    fail(f"invalid GitHub API response: {error}")
if not isinstance(release, dict):
    fail("GitHub API response is not a release object")
tag = release.get("tag_name")
if not isinstance(tag, str) or not tag.startswith("v"):
    fail("release tag must use the v<SemVer> format")
version = tag[1:]
match = pattern.fullmatch(version)
if not match:
    fail(f"release tag {tag!r} is not SemVer")
prerelease = match.group(4)
if prerelease:
    for identifier in prerelease.split("."):
        if identifier.isdigit() and len(identifier) > 1 and identifier.startswith("0"):
            fail(f"numeric prerelease identifier has a leading zero: {identifier}")
if release.get("draft") is not False:
    fail("draft releases cannot be installed")
is_prerelease = release.get("prerelease")
if not isinstance(is_prerelease, bool):
    fail("release channel metadata is missing")
version_is_prerelease = "-" in version.split("+", 1)[0]
if is_prerelease != version_is_prerelease:
    fail("release prerelease flag does not match its SemVer version")
requested = sys.argv[1]
if requested and version != requested:
    fail(f"GitHub returned v{version} for an exact request for v{requested}")
if not requested and is_prerelease:
    fail("the latest stable endpoint returned a prerelease")
print(version)
' "$requested_version"
}

usage() {
    cat <<'USAGE'
Usage: bash install.sh [--install | --update | --repair | --cancel] [--version X.Y.Z]

Modes:
  --install  Install into a new directory (the default on first install)
  --update   Update an existing Git checkout to the latest stable release
  --repair   Run setup for an existing installation without fetching a release
  --cancel   Exit without changing the installation
  --version  Select an exact published SemVer release, including a beta/RC
  --help     Show this help
USAGE
}

INSTALL_MODE=""

parse_install_mode() {
    local version_option_seen=0
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
            --version)
                if (( version_option_seen )); then
                    log_error "Specify --version only once."
                    exit 2
                fi
                if [[ $# -lt 2 ]]; then
                    log_error "--version requires a SemVer value such as 1.2.3."
                    exit 2
                fi
                version_option_seen=1
                shift
                REQUESTED_VERSION="$1"
                if ! is_valid_semver "$REQUESTED_VERSION"; then
                    log_error "Invalid SemVer release version: $REQUESTED_VERSION"
                    exit 2
                fi
                ;;
            --version=*)
                if (( version_option_seen )); then
                    log_error "Specify --version only once."
                    exit 2
                fi
                version_option_seen=1
                REQUESTED_VERSION="${1#--version=}"
                if ! is_valid_semver "$REQUESTED_VERSION"; then
                    log_error "Invalid SemVer release version: $REQUESTED_VERSION"
                    exit 2
                fi
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

    if [[ -n "$REQUESTED_VERSION" && ( "$INSTALL_MODE" == "repair" || "$INSTALL_MODE" == "cancel" ) ]]; then
        log_error "--version can be used only with --install or --update."
        exit 2
    fi
}

resolve_repair_setup_dir() {
    local canonical_install_dir
    if ! canonical_install_dir="$(cd -- "$INSTALL_DIR" && pwd -P)"; then
        log_error "Cannot resolve the installation directory for repair: $INSTALL_DIR"
        return 2
    fi
    SETUP_APP_DIR="$canonical_install_dir"
    if [[ -L "$canonical_install_dir/current" ]]; then
        local current_release releases_dir setup_script
        if ! current_release="$(readlink -f -- "$canonical_install_dir/current")"; then
            log_error "Cannot resolve the active release link for repair."
            return 2
        fi
        releases_dir="$canonical_install_dir/releases"
        case "$current_release" in
            "$releases_dir"/*) ;;
            *)
                log_error "The active release link points outside $releases_dir."
                return 2
                ;;
        esac
        if [[ ! -d "$current_release" || \
            ! -d "$current_release/installer" || -L "$current_release/installer" || \
            ! -f "$current_release/installer/setup.sh" || \
            -L "$current_release/installer/setup.sh" ]]; then
            log_error "The active release does not contain a safe installer/setup.sh."
            return 2
        fi
        if ! setup_script="$(readlink -f -- "$current_release/installer/setup.sh")" || \
            [[ "$setup_script" != "$current_release/"* ]]; then
            log_error "The active release setup script resolves outside the release directory."
            return 2
        fi
        SETUP_APP_DIR="$current_release"
    elif [[ -e "$canonical_install_dir/current" ]]; then
        log_error "The current release path exists but is not a release symlink."
        return 2
    elif [[ ! -d "$canonical_install_dir/installer" || -L "$canonical_install_dir/installer" || \
        ! -f "$canonical_install_dir/installer/setup.sh" || -L "$canonical_install_dir/installer/setup.sh" ]]; then
        log_error "Cannot repair $canonical_install_dir: installer/setup.sh is missing or unsafe."
        return 2
    else
        local legacy_setup_script
        if ! legacy_setup_script="$(readlink -f -- "$canonical_install_dir/installer/setup.sh")" || \
            [[ "$legacy_setup_script" != "$canonical_install_dir/"* ]]; then
            log_error "The legacy setup script resolves outside the installation directory."
            return 2
        fi
    fi
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
                resolve_repair_setup_dir || exit 2
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
    local os_release_file="${1:-/etc/os-release}"
    if [[ ! -f "$os_release_file" ]]; then
        log_error "Cannot detect OS. /etc/os-release not found."
        exit 1
    fi

    . "$os_release_file"
    local os_id="${ID:-}"
    local os_id_like="${ID_LIKE:-}"
    local os_pretty_name="${PRETTY_NAME:-unknown distribution}"
    if [[ "$os_id" != "debian" ]] && [[ "$os_id_like" != *"debian"* ]]; then
        log_warning "This installer is designed for Debian-based systems (DietPi, Raspbian, Ubuntu)."
        log_warning "Detected OS: $os_pretty_name"
        echo -ne "Continue anyway? (y/N) " >&2
        read -n 1 -r < /dev/tty
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            exit 1
        fi
    else
        log_info "Detected OS: $os_pretty_name"
    fi
}

check_installer_python() {
    local python_version python_major python_minor
    if ! command -v python3 >/dev/null 2>&1; then
        log_error "Python 3.11 or newer is required, but python3 was not found."
        return 1
    fi
    if ! python_version="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')" ||
       [[ ! "$python_version" =~ ^[0-9]+\.[0-9]+$ ]]; then
        log_error "Could not determine the system Python version; install Python 3.11 or newer."
        return 1
    fi
    IFS=. read -r python_major python_minor <<<"$python_version"
    if (( python_major < 3 || (python_major == 3 && python_minor < 11) )); then
        log_error "Python 3.11 or newer is required; found Python $python_version."
        return 1
    fi
}

check_installer_disk_space() {
    local install_dir="$1" disk_path df_output available_kib=""
    local filesystem blocks used available rest
    local minimum_free_kib=1048576

    disk_path="$install_dir"
    while [[ ! -e "$disk_path" ]]; do
        if [[ "$disk_path" == */* ]]; then
            disk_path="${disk_path%/*}"
            [[ -n "$disk_path" ]] || disk_path="/"
        else
            disk_path="."
        fi
    done
    if ! df_output="$(df -Pk "$disk_path" 2>/dev/null)"; then
        log_error "Could not check free disk space for $install_dir."
        return 1
    fi
    while read -r filesystem blocks used available rest; do
        if [[ "$available" =~ ^[0-9]+$ ]]; then
            available_kib="$available"
        fi
    done <<<"$df_output"
    if [[ ! "$available_kib" =~ ^[0-9]+$ ]]; then
        log_error "Could not read available disk space for $install_dir."
        return 1
    fi
    if (( available_kib < minimum_free_kib )); then
        log_error "At least 1 GiB of free space is required on the filesystem containing $install_dir; found $((available_kib / 1024)) MiB."
        return 1
    fi
}

verify_venv_support() (
    local probe_parent="$INSTALL_DIR" probe_root parent
    while [[ ! -d "$probe_parent" ]]; do
        parent="${probe_parent%/*}"
        if [[ "$parent" == "$probe_parent" ]]; then
            probe_parent="/"
        else
            probe_parent="${parent:-/}"
        fi
    done
    if ! probe_root="$(sudo mktemp -d "$probe_parent/.knxoh-preflight.XXXXXX")"; then
        log_error "Could not create a temporary directory to test Python virtual environment support."
        exit 1
    fi
    trap 'sudo rm -rf -- "$probe_root"' EXIT
    if ! sudo python3 -m venv "$probe_root/venv" >/dev/null 2>&1; then
        log_error "Could not create a temporary Python virtual environment; check the python3-venv package."
        exit 1
    fi
    if [[ ! -x "$probe_root/venv/bin/python" ]] ||
       ! sudo "$probe_root/venv/bin/python" -c 'import sys' >/dev/null 2>&1; then
        log_error "The temporary Python virtual environment is not usable."
        exit 1
    fi
    log_success "Python virtual environment support is available."
)

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

check_sudo_installer_python() {
    local python_version python_major python_minor
    if ! python_version="$(sudo python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')" ||
       [[ ! "$python_version" =~ ^[0-9]+\.[0-9]+$ ]]; then
        log_error "Could not determine the Python version available through sudo."
        return 1
    fi
    python_major="${python_version%%.*}"
    python_minor="${python_version#*.}"
    if (( python_major < 3 || (python_major == 3 && python_minor < 11) )); then
        log_error "Python 3.11 or newer must be available through sudo as python3; found $python_version."
        return 1
    fi
    log_success "Sudo uses supported Python $python_version."
}

install_dependencies() {
    log_info "Installing system dependencies..."
    local package_lists_updated=0
    local package_status
    
    local packages=(
        "git"
        "python3"
        "python3-venv"
        "python3-pip"
        "rsync"
        "curl"
    )
    
    for pkg in "${packages[@]}"; do
        if ! package_status="$(dpkg-query -W -f='${db:Status-Status}' -- "$pkg" 2>/dev/null)" ||
           [[ "$package_status" != "installed" ]]; then
            if (( package_lists_updated == 0 )); then
                if ! sudo apt-get update -qq; then
                    log_error "Failed to update system package lists"
                    return 1
                fi
                package_lists_updated=1
            fi
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

run_git_as_service_user() {
    if id -u knxohui >/dev/null 2>&1; then
        sudo -u knxohui "$@"
    else
        "$@"
    fi
}

update_repository() {
    if [[ -L "$INSTALL_DIR/current" ]]; then
        log_error "This installation uses transactional releases. Update it from the Web UI; the CLI updater does not activate releases."
        exit 1
    fi

    log_info "Updating installation to release $RELEASE_TAG..."
    if [[ -z "$REQUESTED_VERSION" ]]; then
        local installed_tag
        installed_tag="$(run_git_as_service_user git -C "$INSTALL_DIR" \
            describe --tags --exact-match HEAD 2>/dev/null || true)"
        if [[ "$installed_tag" == v* ]] &&
           is_valid_semver "${installed_tag#v}" &&
           is_version_older "$RELEASE_VERSION" "${installed_tag#v}"; then
            log_info "Keeping installed release $installed_tag; latest stable release $RELEASE_TAG is older."
            return 0
        fi
    fi

    if ! run_git_as_service_user git -C "$INSTALL_DIR" diff --quiet HEAD --; then
        log_error "Tracked application files have local changes; update stopped without changing them."
        exit 1
    fi
    if ! run_git_as_service_user git -C "$INSTALL_DIR" diff --cached --quiet; then
        log_error "The installation has staged local changes; update stopped without changing them."
        exit 1
    fi
    if ! run_git_as_service_user git -C "$INSTALL_DIR" fetch --depth 1 origin \
        "refs/tags/$RELEASE_TAG:refs/tags/$RELEASE_TAG"; then
        log_error "Failed to fetch release $RELEASE_TAG."
        exit 1
    fi

    local current_commit
    local target_commit
    if ! current_commit="$(run_git_as_service_user git -C "$INSTALL_DIR" rev-parse HEAD)" ||
       ! target_commit="$(run_git_as_service_user git -C "$INSTALL_DIR" rev-parse "$RELEASE_TAG^{commit}")"; then
        log_error "Could not identify the installed and selected release commits."
        exit 1
    fi
    if [[ "$current_commit" == "$target_commit" ]]; then
        log_success "Release $RELEASE_TAG is already installed."
        return 0
    fi
    if ! run_git_as_service_user git -C "$INSTALL_DIR" checkout --detach "$RELEASE_TAG"; then
        log_error "Could not switch the clean checkout to release $RELEASE_TAG."
        exit 1
    fi

    log_success "Repository updated to $RELEASE_TAG"
}

clone_repository() {
    if [[ "$INSTALL_MODE" == "update" ]]; then
        update_repository
        return 0
    fi

    if [[ "$INSTALL_MODE" == "repair" ]]; then
        log_info "Repairing the existing installation without pulling source..."
        return 0
    fi

    log_info "Cloning release $RELEASE_TAG from $REPO_URL..."
    TEMP_DIR=$(mktemp -d)
    if ! git clone --depth 1 --single-branch --branch "$RELEASE_TAG" "$REPO_URL" "$TEMP_DIR/repository"; then
        rm -rf "$TEMP_DIR"
        log_error "Failed to clone release $RELEASE_TAG"
        exit 1
    fi
    sudo install -d -m 0755 "$INSTALL_DIR"
    sudo rsync -a "$TEMP_DIR/repository/" "$INSTALL_DIR/"
    rm -rf "$TEMP_DIR"

    log_success "Release $RELEASE_TAG cloned successfully"
}

run_setup_script() {
    log_info "Running setup script..."

    SETUP_APP_DIR="${SETUP_APP_DIR:-$INSTALL_DIR}"
    if ! SETUP_APP_DIR="$(cd -- "$SETUP_APP_DIR" && pwd -P)"; then
        log_error "Cannot resolve the setup directory: $SETUP_APP_DIR"
        exit 1
    fi
    local canonical_setup_script
    if [[ ! -d "$SETUP_APP_DIR/installer" || -L "$SETUP_APP_DIR/installer" || \
        ! -f "$SETUP_APP_DIR/installer/setup.sh" || -L "$SETUP_APP_DIR/installer/setup.sh" ]] || \
        ! canonical_setup_script="$(readlink -f -- "$SETUP_APP_DIR/installer/setup.sh")" || \
        [[ "$canonical_setup_script" != "$SETUP_APP_DIR/"* ]]; then
        log_error "Setup script not found or unsafe at $SETUP_APP_DIR/installer/setup.sh"
        exit 1
    fi

    cd "$SETUP_APP_DIR"
    if bash installer/setup.sh; then
        :
    else
        local setup_status=$?
        log_error "Setup script failed (status $setup_status)"
        return "$setup_status"
    fi
    
    log_success "Setup completed successfully"
}

display_completion() {
    local ip_addresses=$(hostname -I)
    local ip_address="${ip_addresses%% *}"
    local ui_settings
    ui_settings=$(sudo python3 "${SETUP_APP_DIR:-$INSTALL_DIR}/installer/web_ui_endpoint.py" \
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
    if [[ "$INSTALL_MODE" == "cancel" ]]; then
        select_install_mode
    fi
    if ! check_installer_python; then
        exit 1
    fi
    if [[ -z "$INSTALL_DIR" ]]; then
        INSTALL_DIR="$(read_saved_install_dir)"
    fi
    if [[ -z "$CONFIG_DIR" ]]; then
        CONFIG_DIR="$(read_saved_config_dir)"
    fi
    select_install_mode
    if [[ "$INSTALL_MODE" == "update" && -L "$INSTALL_DIR/current" ]]; then
        log_error "This installation uses transactional releases. Update it from the Web UI; the CLI updater does not activate releases."
        exit 2
    fi
    if [[ -n "$REQUESTED_VERSION" && "$INSTALL_MODE" != "install" && "$INSTALL_MODE" != "update" ]]; then
        log_error "--version can be used only with --install or --update."
        exit 2
    fi

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
    if ! check_installer_disk_space "$INSTALL_DIR"; then
        exit 1
    fi
    check_sudo
    if [[ "$INSTALL_MODE" == "install" || "$INSTALL_MODE" == "update" ]]; then
        if ! RELEASE_VERSION="$(resolve_release_version "$REQUESTED_VERSION")"; then
            exit 1
        fi
        RELEASE_TAG="v$RELEASE_VERSION"
        if [[ -n "$REQUESTED_VERSION" ]]; then
            log_info "Selected exact release $RELEASE_TAG."
        else
            log_info "Using the latest stable release $RELEASE_TAG."
        fi
    fi
    install_dependencies
    if ! check_sudo_installer_python; then
        exit 1
    fi
    if ! verify_venv_support; then
        exit 1
    fi
    clone_repository
    run_setup_script
    display_completion
}

# Parse options before checks that can access the system.
if [[ "${BASH_SOURCE[0]:-}" == "$0" || -z "${BASH_SOURCE[0]:-}" ]]; then
    parse_install_mode "$@"
    main
fi
