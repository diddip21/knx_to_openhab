#!/usr/bin/env bash
# One-command installer for KNX to OpenHAB Generator.
# Usage: curl -fsSL https://raw.githubusercontent.com/diddip21/knx_to_openhab/main/install.sh | bash

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

PATHS_FILE="${KNXOH_PATHS_FILE:-/etc/knx_to_openhab/paths.env}"
STABLE_RELEASE_API_URL="${KNXOH_STABLE_RELEASE_API_URL:-https://api.github.com/repos/diddip21/knx_to_openhab/releases/latest}"
PRERELEASE_RELEASES_API_URL="${KNXOH_PRERELEASE_RELEASES_API_URL:-https://api.github.com/repos/diddip21/knx_to_openhab/releases?per_page=100}"
RELEASE_CHANNEL="stable"
ACTION=""
PLAN_ONLY=0
RELEASE_TEMP_DIR=""

cleanup_release_temp() {
    if [[ -n "$RELEASE_TEMP_DIR" ]]; then
        rm -rf -- "$RELEASE_TEMP_DIR"
        RELEASE_TEMP_DIR=""
    fi
}
trap cleanup_release_temp EXIT

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
log_warning() { echo -e "${YELLOW}[WARNING]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1" >&2; }
has_controlling_terminal() {
    [[ "${KNXOH_NONINTERACTIVE:-0}" != "1" ]] &&
        [[ -e /dev/tty ]] && ( : </dev/tty ) 2>/dev/null
}

read_saved_path() {
    python3 - "$PATHS_FILE" "$1" "$2" <<'PY'
import shlex
import sys

path_file, wanted, fallback = sys.argv[1:]
try:
    lines = open(path_file, encoding="utf-8").read().splitlines()
except FileNotFoundError:
    print(fallback)
    raise SystemExit(0)
for line in lines:
    if "=" not in line:
        continue
    name, value = line.strip().split("=", 1)
    if name == wanted:
        parsed = shlex.split(value, posix=True)
        if len(parsed) == 1:
            print(parsed[0])
            raise SystemExit(0)
print(fallback)
PY
}

INSTALL_DIR="${KNXOH_INSTALL_DIR:-$(read_saved_path KNXOH_INSTALL_DIR /opt/knx_to_openhab)}"
CONFIG_DIR="${KNXOH_CONFIG_DIR:-$(read_saved_path KNXOH_CONFIG_DIR /etc/knx_to_openhab)}"
DATA_DIR="${KNXOH_DATA_DIR:-$(read_saved_path KNXOH_DATA_DIR /var/lib/knx_to_openhab)}"
BACKUP_DIR="${KNXOH_BACKUP_DIR:-$(read_saved_path KNXOH_BACKUP_DIR /var/backups/knx_to_openhab)}"

usage() {
    cat <<'EOF'
Usage: install.sh [--plan] [--update | --repair | --reinstall | --cancel]
                  [--channel stable|prerelease]

Stable releases are installed by default. Prereleases require --channel prerelease.
--repair restores missing system components without migrating or replacing user data.
--plan shows the selected action without making changes.
EOF
}

parse_arguments() {
    while (($#)); do
        case "$1" in
            --plan) PLAN_ONLY=1 ;;
            --update|--repair|--reinstall|--cancel)
                if [[ -n "$ACTION" ]]; then
                    log_error "Choose only one lifecycle action."
                    return 2
                fi
                ACTION="${1#--}"
                ;;
            --channel)
                shift
                if (($# == 0)) || [[ "$1" != "stable" && "$1" != "prerelease" ]]; then
                    log_error "--channel must be stable or prerelease."
                    return 2
                fi
                RELEASE_CHANNEL="$1"
                ;;
            --help|-h) usage; exit 0 ;;
            *) log_error "Unknown option: $1"; usage >&2; return 2 ;;
        esac
        shift
    done
}

classify_installation() {
    local install_path="$INSTALL_DIR"
    local release_path="$install_path/releases"
    local candidate
    HAS_INSTALLATION=0
    HAS_ACTIVE_INSTALL=0
    INTERRUPTED_INSTALL=0
    CURRENT_RELEASE=""

    if [[ -e "$install_path" || -L "$install_path" ]]; then
        HAS_INSTALLATION=1
    fi
    if [[ -L "$install_path/current" ]]; then
        if [[ -e "$install_path/current" ]]; then
            HAS_ACTIVE_INSTALL=1
            CURRENT_RELEASE="$(basename "$(readlink -f "$install_path/current")")"
        else
            INTERRUPTED_INSTALL=1
        fi
    elif [[ -e "$install_path/current" ]]; then
        log_error "Refusing to replace non-symlink path $install_path/current."
        return 2
    elif [[ -f "$install_path/installer/setup.sh" ]]; then
        HAS_ACTIVE_INSTALL=1
        CURRENT_RELEASE="legacy"
    fi

    if [[ -L "$release_path" ]]; then
        log_error "The releases directory must not be a symlink: $release_path"
        return 2
    fi
    if [[ -e "$release_path" && ! -d "$release_path" ]]; then
        log_error "The releases path must be a directory: $release_path"
        return 2
    fi
    if [[ -d "$release_path" ]]; then
        for candidate in "$release_path"/.*.staging.*; do
            if [[ -e "$candidate" || -L "$candidate" ]]; then
                INTERRUPTED_INSTALL=1
            fi
        done
        for candidate in "$release_path"/*; do
            if [[ -d "$candidate" && -f "$candidate/.install-incomplete" ]]; then
                INTERRUPTED_INSTALL=1
            fi
        done
        if [[ "$HAS_ACTIVE_INSTALL" -eq 0 ]]; then
            for candidate in "$release_path"/*; do
                if [[ -d "$candidate" && ! -L "$candidate" ]]; then
                    INTERRUPTED_INSTALL=1
                    break
                fi
            done
        fi
    fi
}

plan_action() {
    local explicit_action="$ACTION"
    classify_installation || return $?

    if [[ "$ACTION" == "cancel" ]]; then
        return 0
    fi
    if [[ -n "$explicit_action" ]]; then
        if [[ "$explicit_action" == "repair" && "$HAS_ACTIVE_INSTALL" -eq 0 && "$INTERRUPTED_INSTALL" -eq 0 ]]; then
            log_error "No active or interrupted installation is available to repair."
            return 2
        fi
        return 0
    fi
    if [[ "$HAS_INSTALLATION" -eq 0 ]]; then
        ACTION="install"
        return 0
    fi
    if [[ "$INTERRUPTED_INSTALL" -eq 1 && "$HAS_ACTIVE_INSTALL" -eq 0 ]]; then
        ACTION="repair"
        if [[ "$PLAN_ONLY" -eq 1 ]] || has_controlling_terminal; then
            return 0
        fi
        ACTION=""
        log_error "An interrupted installation was found. In non-interactive mode, choose --update, --repair, --reinstall, or --cancel."
        return 2
    fi
    if ! has_controlling_terminal; then
        log_error "An existing installation was found. In non-interactive mode, choose --update, --repair, --reinstall, or --cancel."
        return 2
    fi

    echo "An existing KNX to OpenHAB installation was found at $INSTALL_DIR." >/dev/tty
    echo "[u] Update stable release  [r] Repair missing system components" >/dev/tty
    echo "[i] Reinstall stable release  [c] Cancel (default)" >/dev/tty
    printf "Choose an action: " >/dev/tty
    local choice=""
    read -r choice </dev/tty || choice=""
    case "${choice,,}" in
        u|update) ACTION="update" ;;
        r|repair) ACTION="repair" ;;
        i|reinstall) ACTION="reinstall" ;;
        c|cancel|"") ACTION="cancel" ;;
        *) log_error "Unknown action '$choice'; no changes were made."; return 2 ;;
    esac
}

print_plan() {
    local channel=""
    local source="installed-release"
    if [[ "$ACTION" == "install" || "$ACTION" == "update" || "$ACTION" == "reinstall" ]]; then
        channel="$RELEASE_CHANNEL"
        source="github-release"
    elif [[ "$ACTION" == "repair" && "$INTERRUPTED_INSTALL" -eq 1 && "$HAS_ACTIVE_INSTALL" -eq 0 ]]; then
        channel="$RELEASE_CHANNEL"
        source="github-release-recovery"
    fi
    python3 - "$ACTION" "$channel" "$INSTALL_DIR" "$source" "$INTERRUPTED_INSTALL" <<'PY'
import json
import sys

action, channel, install_dir, source, interrupted = sys.argv[1:]
plan = {
    "action": action,
    "channel": channel or None,
    "install_dir": install_dir,
    "source": source,
}
if interrupted == "1":
    plan["interrupted_install"] = True
print(json.dumps(plan, sort_keys=True))
PY
}

check_root() {
    if [[ $EUID -eq 0 && "${ALLOW_ROOT:-0}" != "1" ]]; then
        log_error "Do not run this script as root; use a regular account with sudo access."
        exit 1
    fi
}

check_os() {
    if [[ ! -f /etc/os-release ]]; then
        log_error "Cannot detect OS. /etc/os-release not found."
        exit 1
    fi
    # shellcheck disable=SC1091
    . /etc/os-release
    if [[ "${ID:-}" != "debian" && "${ID_LIKE:-}" != *"debian"* ]]; then
        log_warning "This installer is designed for Debian-based systems (DietPi, Raspbian, Ubuntu)."
        log_warning "Detected OS: ${PRETTY_NAME:-unknown}"
        if ! has_controlling_terminal; then
            log_error "Cannot request confirmation in non-interactive mode."
            exit 1
        fi
        printf "Continue anyway? (y/N) " >/dev/tty
        local answer=""
        read -r -n 1 answer </dev/tty || answer=""
        echo >/dev/tty
        [[ "$answer" =~ ^[Yy]$ ]] || exit 1
    else
        log_info "Detected OS: ${PRETTY_NAME:-Debian-based Linux}"
    fi
}

check_sudo() {
    if ! sudo -n true 2>/dev/null; then
        if ! has_controlling_terminal; then
            log_error "Sudo access is required; non-interactive sudo authentication is unavailable."
            exit 1
        fi
        log_info "Testing sudo access..."
        sudo -v || { log_error "This installer requires sudo privileges."; exit 1; }
    fi
    log_success "Sudo access confirmed"
}

install_dependencies() {
    local repair_mode="${1:-0}"
    local packages=(python3 python3-venv python3-pip rsync curl tar)
    local missing=()
    local package
    for package in "${packages[@]}"; do
        if ! dpkg -s "$package" 2>/dev/null | grep -q '^Status: install ok installed$'; then
            missing+=("$package")
        fi
    done
    if ((${#missing[@]} == 0)); then
        log_success "All required system dependencies are installed"
        return 0
    fi
    if [[ "$repair_mode" != "1" ]]; then
        log_info "Refreshing package metadata..."
        sudo apt-get update -qq
    fi
    log_info "Installing missing dependencies: ${missing[*]}"
    sudo apt-get install -y -qq "${missing[@]}" || {
        log_error "Failed to install required system dependencies."
        return 1
    }
}

release_api_url() {
    if [[ "$RELEASE_CHANNEL" == "stable" ]]; then
        printf '%s\n' "$STABLE_RELEASE_API_URL"
    else
        printf '%s\n' "$PRERELEASE_RELEASES_API_URL"
    fi
}

read_release_metadata() {
    local metadata_file="$1"
    python3 - "$metadata_file" "$RELEASE_CHANNEL" <<'PY'
import json
import re
import sys

metadata_path, channel = sys.argv[1:]
try:
    with open(metadata_path, encoding="utf-8") as source:
        releases = json.load(source)
except (OSError, json.JSONDecodeError) as error:
    raise SystemExit(f"Invalid GitHub release metadata: {error}")
if isinstance(releases, dict):
    releases = [releases]
if not isinstance(releases, list):
    raise SystemExit("GitHub release metadata must be an object or list")

pattern = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
                     r"(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
                     r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$")
for release in releases:
    if not isinstance(release, dict) or bool(release.get("draft")):
        continue
    is_prerelease = bool(release.get("prerelease"))
    if is_prerelease != (channel == "prerelease"):
        continue
    tag = release.get("tag_name", "")
    if not isinstance(tag, str) or not tag.startswith("v"):
        continue
    version = tag[1:]
    if not pattern.fullmatch(version):
        continue
    version_without_build = version.split("+", 1)[0]
    prerelease_identifier = version_without_build.partition("-")[2]
    has_prerelease_suffix = bool(prerelease_identifier)
    if has_prerelease_suffix != is_prerelease:
        continue
    if any(
        identifier.isdigit() and len(identifier) > 1 and identifier.startswith("0")
        for identifier in prerelease_identifier.split(".")
    ):
        continue
    archive_name = f"knx_to_openhab-{version}.tar.gz"
    checksum_name = archive_name + ".sha256"
    assets = release.get("assets", [])
    if not isinstance(assets, list):
        continue
    by_name = {asset.get("name"): asset for asset in assets if isinstance(asset, dict)}
    archive = by_name.get(archive_name, {}).get("browser_download_url")
    checksum = by_name.get(checksum_name, {}).get("browser_download_url")
    if isinstance(archive, str) and archive.startswith("https://") and isinstance(checksum, str) and checksum.startswith("https://"):
        print(version)
        print(archive)
        print(checksum)
        raise SystemExit(0)
    raise SystemExit(f"Release {tag} is missing its archive or SHA-256 sidecar")
raise SystemExit(f"No {channel} release with valid archive assets was found")
PY
}

extract_verified_release() {
    local archive="$1"
    local destination="$2"
    local version="$3"
    python3 - "$archive" "$destination" "$version" <<'PY'
import posixpath
import sys
import tarfile
from pathlib import Path, PurePosixPath

archive_path, destination, version = sys.argv[1:]
expected_root = f"knx_to_openhab-{version}"
output = Path(destination)
with tarfile.open(archive_path, "r:gz") as source:
    members = source.getmembers()
    if not members:
        raise SystemExit("Release archive is empty")
    symlinks = set()
    for member in members:
        name = PurePosixPath(member.name)
        if name.is_absolute() or ".." in name.parts or not name.parts or name.parts[0] != expected_root:
            raise SystemExit(f"Unsafe or unexpected archive member: {member.name!r}")
        if not (member.isdir() or member.isfile() or member.issym()):
            raise SystemExit(f"Unsupported archive member type: {member.name!r}")
        for parent in name.parents:
            if parent.as_posix() in symlinks:
                raise SystemExit(f"Archive member traverses a symlink: {member.name!r}")
        if member.issym():
            if not member.linkname or member.linkname.startswith("/"):
                raise SystemExit(f"Unsafe symlink target: {member.name!r}")
            target = posixpath.normpath(posixpath.join(posixpath.dirname(member.name), member.linkname))
            if target != expected_root and not target.startswith(expected_root + "/"):
                raise SystemExit(f"Symlink escapes release root: {member.name!r}")
            symlinks.add(member.name)
    source.extractall(output, members=members, filter="data")
root = output / expected_root
if not (root / "installer/setup.sh").is_file():
    raise SystemExit("Verified release archive does not contain installer/setup.sh")
if (root / "VERSION").read_text(encoding="ascii").strip() != version:
    raise SystemExit("Release VERSION does not match its GitHub tag")
PY
}

validate_setup_source() {
    local source_dir="$1"
    python3 - "$source_dir" "$INSTALL_DIR" "$RELEASE_TEMP_DIR" <<'PY'
import os
import pwd
import stat
import sys
from pathlib import Path

source, install_dir, temporary_root = sys.argv[1:]
try:
    source_root = Path(source).resolve(strict=True)
    setup_script = source_root / "installer/setup.sh"
    setup_target = setup_script.resolve(strict=True)
    if not setup_target.is_file():
        raise ValueError("setup.sh is not a regular file")

    if temporary_root:
        isolated_root = Path(temporary_root).resolve(strict=True)
        if source_root.is_relative_to(isolated_root):
            root_stat = isolated_root.stat()
            if root_stat.st_uid != os.geteuid() or stat.S_IMODE(root_stat.st_mode) & 0o077:
                raise ValueError("verified release extraction directory is not private")
            if not setup_target.is_relative_to(isolated_root):
                raise ValueError("setup script escapes the verified extraction directory")
            raise SystemExit(0)

    base = Path(install_dir).resolve(strict=True)
    releases = base / "releases"
    if not source_root.is_relative_to(releases):
        raise ValueError("setup source is not under the immutable release directory")
    try:
        service_account = pwd.getpwnam("knxohui")
        service_uid = service_account.pw_uid
        service_gids = set(os.getgrouplist(service_account.pw_name, service_account.pw_gid))
    except KeyError:
        service_uid = None
        service_gids = set()

    def require_not_service_writable(path: Path) -> None:
        metadata = path.lstat()
        mode = stat.S_IMODE(metadata.st_mode)
        service_can_write = (
            metadata.st_uid == service_uid
            if service_uid is not None and metadata.st_uid == service_uid
            else bool(
                mode & stat.S_IWGRP
                if metadata.st_gid in service_gids
                else mode & stat.S_IWOTH
            )
            if service_uid is not None
            else bool(mode & 0o022)
        )
        if service_can_write:
            raise ValueError(f"release path is writable by the service account: {path}")

    raw_install = Path(os.path.abspath(install_dir))
    for ancestor in (*reversed(raw_install.parents), raw_install):
        if ancestor.is_symlink():
            raise ValueError(f"installation path contains a symlink: {ancestor}")

    def require_safe_ancestors(path: Path) -> None:
        absolute = Path(os.path.abspath(path))
        chain = [*reversed(absolute.parents), absolute]
        for parent, child in zip(chain, chain[1:]):
            if not parent.exists():
                break
            metadata = parent.lstat()
            if stat.S_ISLNK(metadata.st_mode):
                raise ValueError(f"installation path contains a symlink ancestor: {parent}")
            mode = stat.S_IMODE(metadata.st_mode)
            parent_service_writable = (
                metadata.st_uid == service_uid
                if service_uid is not None and metadata.st_uid == service_uid
                else bool(
                    mode & stat.S_IWGRP
                    if metadata.st_gid in service_gids
                    else mode & stat.S_IWOTH
                )
                if service_uid is not None
                else bool(mode & 0o022)
            )
            if not parent_service_writable:
                continue
            sticky_protects_child = bool(metadata.st_mode & stat.S_ISVTX)
            if sticky_protects_child and metadata.st_uid != service_uid:
                try:
                    child_stat = child.lstat()
                except FileNotFoundError:
                    child_stat = None
                if child_stat is not None and child_stat.st_uid != service_uid:
                    continue
            raise ValueError(f"service-writable ancestor in application path: {parent}")

    for checked_path in (base, releases, source_root):
        require_safe_ancestors(checked_path)
        if checked_path.exists():
            require_not_service_writable(checked_path)

    for current, directories, files in os.walk(source_root, followlinks=False):
        for name in directories + files:
            entry = Path(current) / name
            metadata = entry.lstat()
            if stat.S_ISLNK(metadata.st_mode):
                target = entry.resolve(strict=True)
                if target.is_dir():
                    raise ValueError(f"directory symlinks are not allowed in release trees: {entry}")
                for target_parent in (target, *target.parents):
                    require_not_service_writable(target_parent)
            else:
                require_not_service_writable(entry)
except (OSError, RuntimeError, ValueError) as error:
    print(error, file=sys.stderr)
    raise SystemExit(1)
PY
}

run_setup_script() {
    local source_dir="$1"
    local source_root
    shift
    if ! validate_setup_source "$source_dir"; then
        log_error "Refusing to execute setup from a mutable release tree or untrusted path."
        return 2
    fi
    source_root="$(readlink -f -- "$source_dir")"
    sudo env \
        "KNXOH_INSTALL_DIR=$INSTALL_DIR" \
        "KNXOH_CONFIG_DIR=$CONFIG_DIR" \
        "KNXOH_DATA_DIR=$DATA_DIR" \
        "KNXOH_BACKUP_DIR=$BACKUP_DIR" \
        "KNXOH_PATHS_FILE=$PATHS_FILE" \
        "KNXOH_SETUP_ROOT=$source_root" \
        bash -s -- "$@" <"$source_root/installer/setup.sh"
}

remove_abandoned_staging() {
    local stage
    local release_path="$INSTALL_DIR/releases"
    if [[ -L "$release_path" ]]; then
        log_error "The releases directory must not be a symlink: $release_path"
        return 2
    fi
    [[ -d "$release_path" ]] || return 0
    for stage in "$release_path"/.*.staging.*; do
        [[ -e "$stage" || -L "$stage" ]] || continue
        if [[ -L "$stage" || ! -d "$stage" ]]; then
            log_error "Refusing to remove non-directory release staging path: $stage"
            return 1
        fi
        case "$stage" in
            "$release_path"/.*.staging.*) sudo rm -rf -- "$stage" ;;
            *) log_error "Refusing an unexpected release staging path: $stage"; return 1 ;;
        esac
    done
}

install_release() {
    local temporary_dir metadata_file version archive_url checksum_url
    local archive_name checksum_name expected_checksum actual_checksum extracted
    temporary_dir="$(mktemp -d)"
    RELEASE_TEMP_DIR="$temporary_dir"
    metadata_file="$temporary_dir/release.json"
    log_info "Looking up the latest $RELEASE_CHANNEL release..."
    curl -fsSL -H 'Accept: application/vnd.github+json' "$(release_api_url)" -o "$metadata_file" || {
        log_error "Could not retrieve release metadata from GitHub."
        return 1
    }
    mapfile -t release_fields < <(read_release_metadata "$metadata_file") || {
        log_error "No valid $RELEASE_CHANNEL release artifact is available."
        return 1
    }
    if ((${#release_fields[@]} != 3)); then
        log_error "GitHub release metadata did not identify a complete artifact."
        return 1
    fi
    version="${release_fields[0]}"
    archive_url="${release_fields[1]}"
    checksum_url="${release_fields[2]}"
    archive_name="knx_to_openhab-$version.tar.gz"
    checksum_name="$archive_name.sha256"

    if [[ "$CURRENT_RELEASE" == "$version" ]]; then
        log_info "Release $version is already active; repairing only missing system components."
        run_setup_script "$INSTALL_DIR/current" --repair
        return $?
    fi
    if [[ -e "$INSTALL_DIR/releases/$version" || -L "$INSTALL_DIR/releases/$version" ]]; then
        if [[ -f "$INSTALL_DIR/releases/$version/.install-incomplete" ]]; then
            log_info "Release $version was interrupted before activation; repairing its system components."
            run_setup_script "$INSTALL_DIR/releases/$version" --repair --activate-existing
            return $?
        fi
        if [[ -d "$INSTALL_DIR/releases/$version" &&
            -f "$INSTALL_DIR/releases/$version/installer/setup.sh" &&
            -f "$INSTALL_DIR/releases/$version/VERSION" &&
            "$(tr -d '\r\n' < "$INSTALL_DIR/releases/$version/VERSION")" == "$version" ]]; then
            log_info "Release $version is already installed; activating it without replacing its files."
            run_setup_script "$INSTALL_DIR/releases/$version" --repair --activate-existing
            return $?
        fi
        log_error "Release $version exists but is not a complete immutable release; refusing to replace it."
        return 2
    fi

    curl -fsSL "$archive_url" -o "$temporary_dir/$archive_name" || {
        log_error "Could not download release archive $archive_name."
        return 1
    }
    curl -fsSL "$checksum_url" -o "$temporary_dir/$checksum_name" || {
        log_error "Could not download release checksum $checksum_name."
        return 1
    }
    expected_checksum="$(python3 - "$temporary_dir/$checksum_name" "$archive_name" <<'PY'
import re
import sys

contents = open(sys.argv[1], encoding="ascii").read()
match = re.fullmatch(r"([0-9a-fA-F]{64})[ \t]+[* ]?" + re.escape(sys.argv[2]) + r"\n?", contents)
if not match:
    raise SystemExit("Release checksum sidecar has an invalid format or filename")
print(match.group(1).lower())
PY
)" || {
        log_error "Release checksum sidecar is invalid."
        return 1
    }
    actual_checksum="$(python3 - "$temporary_dir/$archive_name" <<'PY'
import hashlib
import sys

digest = hashlib.sha256()
with open(sys.argv[1], "rb") as source:
    for block in iter(lambda: source.read(1024 * 1024), b""):
        digest.update(block)
print(digest.hexdigest())
PY
)"
    if [[ "$actual_checksum" != "$expected_checksum" ]]; then
        log_error "SHA-256 verification failed for $archive_name."
        return 1
    fi
    log_success "Verified SHA-256 for $archive_name"

    extracted="$temporary_dir/extracted"
    mkdir -p "$extracted"
    extract_verified_release "$temporary_dir/$archive_name" "$extracted" "$version" || {
        log_error "Release archive failed safe extraction validation."
        return 1
    }
    run_setup_script "$extracted/knx_to_openhab-$version"
}

repair_installation() {
    local source_dir="" candidate recovery_release=""
    if [[ "$INTERRUPTED_INSTALL" -eq 1 ]]; then
        remove_abandoned_staging || return $?
        if [[ -d "$INSTALL_DIR/releases" ]]; then
            for candidate in "$INSTALL_DIR/releases"/*; do
                if [[ -d "$candidate" && -f "$candidate/.install-incomplete" ]]; then
                    recovery_release="$candidate"
                fi
            done
        fi
    fi
    if [[ -n "$recovery_release" ]]; then
        run_setup_script "$recovery_release" --repair --activate-existing
        return $?
    fi
    if [[ "$CURRENT_RELEASE" == "legacy" ]]; then
        log_error "Legacy flat installations cannot be safely repaired in place. Use --update to migrate into a verified immutable release."
        return 2
    fi
    if [[ -L "$INSTALL_DIR/current" && -e "$INSTALL_DIR/current" ]]; then
        source_dir="$INSTALL_DIR/current"
    elif [[ "$CURRENT_RELEASE" == "legacy" ]]; then
        source_dir="$INSTALL_DIR"
    elif [[ -d "$INSTALL_DIR/releases" ]]; then
        local candidate
        for candidate in "$INSTALL_DIR/releases"/*; do
            if [[ -d "$candidate" && ! -L "$candidate" ]]; then
                source_dir="$candidate"
            fi
        done
    fi
    if [[ -n "$source_dir" ]]; then
        run_setup_script "$source_dir" --repair
        return $?
    fi

    if [[ "$INTERRUPTED_INSTALL" -eq 1 ]]; then
        log_warning "Only incomplete staging data was found; restaging from the selected release channel."
        install_release
        return $?
    fi
    log_error "No usable application release was found to repair."
    return 2
}

display_completion() {
    local app_dir="$INSTALL_DIR/current"
    if [[ ! -d "$app_dir" ]]; then
        app_dir="$INSTALL_DIR"
    fi
    local ip_addresses="$(hostname -I)"
    local ui_settings
    ui_settings=$(sudo python3 "$app_dir/installer/web_ui_endpoint.py" \
        --config "$CONFIG_DIR/config.json" --lan-ip "$ip_addresses")
    local -a ui_values=()
    mapfile -t ui_values <<<"$ui_settings"
    local ui_host="${ui_values[1]:-127.0.0.1}"
    local port="${ui_values[2]:-8085}"
    echo ""
    echo -e "${GREEN}KNX to OpenHAB Generator is ready.${NC}"
    echo -e "  Application: $app_dir"
    echo -e "  Web UI: http://$ui_host:$port"
    echo -e "  Settings and secrets remain under: $CONFIG_DIR"
}

main() {
    parse_arguments "$@" || return $?
    plan_action || return $?
    if [[ "$ACTION" == "cancel" ]]; then
        if [[ "$PLAN_ONLY" -eq 1 ]]; then
            print_plan
            return 0
        fi
        log_info "Cancelled; no changes were made."
        return 0
    fi
    if [[ "$PLAN_ONLY" -eq 1 ]]; then
        print_plan
        return 0
    fi

    check_root
    check_os
    check_sudo
    if [[ "$ACTION" == "repair" ]]; then
        install_dependencies 1
        repair_installation
    else
        install_dependencies
        install_release
    fi
    display_completion
}

main "$@"
