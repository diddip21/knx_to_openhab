#!/usr/bin/env bash
set -euo pipefail

if [[ -n "${KNXOH_SETUP_ROOT:-}" ]]; then
    SCRIPT_DIR="$KNXOH_SETUP_ROOT/installer"
else
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
fi
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PATHS_FILE="${KNXOH_PATHS_FILE:-/etc/knx_to_openhab/paths.env}"
SERVICE_USER="knxohui"
SETUP_MODE="install"
ACTIVATE_EXISTING=0
for argument in "$@"; do
    case "$argument" in
        --repair) SETUP_MODE="repair" ;;
        --activate-existing) ACTIVATE_EXISTING=1 ;;
        *) echo "Unknown setup option: $argument" >&2; exit 2 ;;
    esac
done
if [[ "$ACTIVATE_EXISTING" -eq 1 && "$SETUP_MODE" != "repair" ]]; then
    echo "--activate-existing is valid only with --repair." >&2
    exit 2
fi

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

BASE="${KNXOH_INSTALL_DIR:-$(read_saved_path KNXOH_INSTALL_DIR /opt/knx_to_openhab)}"
CONFIG_DIR="${KNXOH_CONFIG_DIR:-$(read_saved_path KNXOH_CONFIG_DIR /etc/knx_to_openhab)}"
DATA_DIR="${KNXOH_DATA_DIR:-$(read_saved_path KNXOH_DATA_DIR /var/lib/knx_to_openhab)}"
BACKUP_DIR="${KNXOH_BACKUP_DIR:-$(read_saved_path KNXOH_BACKUP_DIR /var/backups/knx_to_openhab)}"

NORMALIZED_PATHS=$(python3 - "$BASE" "$CONFIG_DIR" "$DATA_DIR" "$BACKUP_DIR" <<'PY'
import os
import pwd
import stat
import sys
from pathlib import Path

if any(ord(c) < 32 or c in '\\"%$\x7f' for value in sys.argv[1:] for c in value):
    raise SystemExit("Unsupported installation path characters")
raw_paths = [Path(value).expanduser() for value in sys.argv[1:]]
for path in raw_paths:
    if not path.is_absolute():
        raise SystemExit(f"Installation paths must be absolute: {path}")
raw_base = Path(os.path.abspath(raw_paths[0]))
try:
    account = pwd.getpwnam("knxohui")
    service_uid = account.pw_uid
    service_gids = set(os.getgrouplist(account.pw_name, account.pw_gid))
except KeyError:
    service_uid = None
    service_gids = set()

def service_can_write(metadata):
    mode = stat.S_IMODE(metadata.st_mode)
    if service_uid is not None and metadata.st_uid == service_uid:
        return True
    if service_uid is None:
        return bool(mode & 0o022)
    if metadata.st_gid in service_gids:
        return bool(mode & stat.S_IWGRP)
    return bool(mode & stat.S_IWOTH)

path_chain = [*reversed(raw_base.parents), raw_base]
for parent, child in zip(path_chain, path_chain[1:]):
    if parent.is_symlink():
        raise SystemExit(f"Installation path contains a symlink ancestor: {parent}")
    if not parent.exists():
        break
    metadata = parent.lstat()
    if not service_can_write(metadata):
        continue
    sticky = bool(metadata.st_mode & stat.S_ISVTX) and metadata.st_uid != service_uid
    if sticky and child.exists() and child.lstat().st_uid != service_uid:
        continue
    raise SystemExit(f"Service-writable ancestor in application path: {parent}")
for component in path_chain:
    if component.is_symlink():
        raise SystemExit(f"Installation path contains a symlink: {component}")

base, config, data, backups = (path.resolve() for path in raw_paths)
paths = {"application": base, "configuration": config, "runtime data": data, "backups": backups}
for label, path in paths.items():
    if not path.is_absolute() or path == Path(path.anchor):
        raise SystemExit(f"{label} path must be a non-root absolute path: {path}")
    if label != "application" and (path == base or base in path.parents):
        raise SystemExit(f"{label} must be outside the application directory: {path}")
    if str(path) in {"/etc", "/var", "/usr", "/opt", "/home", "/root", "/tmp"}:
        raise SystemExit(f"Refusing a system-wide path as {label}: {path}")

external = (config, data, backups)
for index, left in enumerate(external):
    for right in external[index + 1 :]:
        if left == right or left in right.parents or right in left.parents:
            raise SystemExit(f"Configuration, runtime and backup paths must not overlap: {left}, {right}")

print(base)
print(config)
print(data)
print(backups)
PY
) || exit 2
mapfile -t NORMALIZED_PATH_LIST <<<"$NORMALIZED_PATHS"
BASE="${NORMALIZED_PATH_LIST[0]}"
CONFIG_DIR="${NORMALIZED_PATH_LIST[1]}"
DATA_DIR="${NORMALIZED_PATH_LIST[2]}"
BACKUP_DIR="${NORMALIZED_PATH_LIST[3]}"

# The verified administrator bootstrap holds ONE lease across all shell writes.
# Nested calls prove ownership of a live inherited descriptor; no boolean bypass.
BOOTSTRAP_ARGS=(--base "$BASE" --config-dir "$CONFIG_DIR" --data-dir "$DATA_DIR"
    --backup-dir "$BACKUP_DIR" --paths-file "$PATHS_FILE")
if [[ -z "${KNXOH_LIFECYCLE_FD:-}" ]]; then
    exec /usr/bin/python3 -I "$REPO_ROOT/installer/update_bootstrap.py" \
        --action setup "${BOOTSTRAP_ARGS[@]}" -- "$@"
fi
/usr/bin/python3 -I "$REPO_ROOT/installer/update_bootstrap.py" \
    --action validate "${BOOTSTRAP_ARGS[@]}"

provision_updater() {
    /usr/bin/python3 -I "$REPO_ROOT/installer/update_bootstrap.py" \
        --action provision "${BOOTSTRAP_ARGS[@]}"
}

check_repair_release() {
    /usr/bin/python3 -I "$REPO_ROOT/installer/update_bootstrap.py" \
        --action check-release "${BOOTSTRAP_ARGS[@]}" -- "$1" "$2"
}

mark_installer_blocked() {
    /usr/bin/python3 -I - "$BASE/.installer-incomplete" <<'PY'
import os
import stat
import sys

path = sys.argv[1]
parent = os.open(os.path.dirname(path), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
try:
    fd = os.open(os.path.basename(path), os.O_RDONLY | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK,
                 0o600, dir_fd=parent)
    try:
        info = os.fstat(fd)
        if info.st_uid != 0 or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ValueError("Unsafe installer deny marker")
        os.fsync(fd)
    finally:
        os.close(fd)
finally:
    os.fsync(parent)
    os.close(parent)
PY
}

finish_protected_stage() {
    local mode="$1" ui_start="$2" ui_enable="$3" cleanup_start="$4" cleanup_enable="$5"
    local previous="$CURRENT_TARGET"
    if [[ -n "$previous" ]]; then
        if [[ "$previous" != /* ]]; then
            previous="$BASE/$previous"
        fi
        previous="$(readlink -f -- "$previous")" || return 1
    fi
    # The parent completes disk mutations under its live lease, then releases it
    # BEFORE starting recovery (which acquires the same lease). No cyclic start.
    python3 - "$KNXOH_BOOTSTRAP_OUTCOME" "$mode" "$RELEASE_DIR" "$previous" \
        "$MIGRATION_SNAPSHOT_PATH_FILE" "${RELEASE_WAS_INCOMPLETE:-0}" "$ui_start" "$ui_enable" \
        "$cleanup_start" "$cleanup_enable" \
        "$UI_WAS_ACTIVE" "$UI_WAS_ENABLED" "$CLEANUP_SERVICE_WAS_ACTIVE" \
        "$CLEANUP_TIMER_WAS_ACTIVE" "$CLEANUP_TIMER_WAS_ENABLED" <<'PY'
import json
import os
import sys

destination, mode, release, previous, snapshot, was_incomplete, *flags = sys.argv[1:]
names = ("ui_start", "ui_enable", "cleanup_start", "cleanup_enable", "ui_was_active",
         "ui_was_enabled", "cleanup_service_was_active", "cleanup_timer_was_active",
         "cleanup_timer_was_enabled")
value = dict(zip(names, [flag == "1" for flag in flags]))
value.update(mode=mode, release=release, previous=previous, snapshot_file=snapshot)
value["release_was_incomplete"] = was_incomplete == "1"
fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
with os.fdopen(fd, "w", encoding="utf-8") as output:
    json.dump(value, output)
    output.flush()
    os.fsync(output.fileno())
PY
    if [[ "$mode" == install ]]; then
        sudo rm -f -- "$RELEASE_DIR/.install-incomplete"
    fi
    # Disk preparation succeeded; service-activation rollback belongs to the
    # trusted parent, after re-acquiring and rechecking the protected contract.
    MIGRATION_STARTED=0
    CURRENT_SWITCHED=0
    SYSTEM_STATE_CAPTURED=0
}

# Package mutations also remain inside the same verified lifecycle lease.
packages=(python3 python3-venv python3-pip rsync curl tar)
missing=()
for package in "${packages[@]}"; do
    if ! dpkg -s "$package" 2>/dev/null | grep -q '^Status: install ok installed$'; then
        missing+=("$package")
    fi
done
if ((${#missing[@]})); then
    if [[ "$SETUP_MODE" != "repair" ]]; then
        sudo apt-get update -qq
    fi
    sudo apt-get install -y -qq "${missing[@]}"
fi

if [[ -L "$BASE/releases" ]]; then
    echo "The releases directory must not be a symlink: $BASE/releases" >&2
    exit 2
fi
if [[ -e "$BASE/releases" && ! -d "$BASE/releases" ]]; then
    echo "The releases path must be a directory: $BASE/releases" >&2
    exit 2
fi

STAGING_DIR=""
RELEASE_DIR=""
RELEASE_WAS_INCOMPLETE=0
CURRENT_LINK_TMP=""
CURRENT_TARGET=""
CURRENT_SWITCHED=0
MIGRATION_SNAPSHOT_PATH_FILE=""
MIGRATION_ROLLBACK_SCRIPT=""
MIGRATION_STARTED=0
TRANSACTION_STATE_FILE=""
SYSTEM_STATE_CAPTURED=0
UI_WAS_ACTIVE=0
CLEANUP_SERVICE_WAS_ACTIVE=0
CLEANUP_TIMER_WAS_ACTIVE=0
UI_WAS_ENABLED=0
CLEANUP_TIMER_WAS_ENABLED=0

capture_system_state() {
    sudo systemctl is-active --quiet knxohui.service && UI_WAS_ACTIVE=1 || true
    sudo systemctl is-active --quiet knxohui-backup-cleanup.service &&
        CLEANUP_SERVICE_WAS_ACTIVE=1 || true
    sudo systemctl is-active --quiet knxohui-backup-cleanup.timer &&
        CLEANUP_TIMER_WAS_ACTIVE=1 || true
    sudo systemctl is-enabled --quiet knxohui.service && UI_WAS_ENABLED=1 || true
    sudo systemctl is-enabled --quiet knxohui-backup-cleanup.timer &&
        CLEANUP_TIMER_WAS_ENABLED=1 || true
    SYSTEM_STATE_CAPTURED=1
}

restore_unit_state() {
    local unit="$1" was_active="$2" was_enabled="$3" active_is_transient="${4:-0}"
    local failed=0
    if [[ -n "$was_enabled" ]]; then
        if [[ "$was_enabled" -eq 1 ]]; then
            sudo systemctl enable "$unit" >/dev/null 2>&1 || failed=1
            sudo systemctl is-enabled --quiet "$unit" || failed=1
        elif sudo systemctl is-enabled --quiet "$unit"; then
            sudo systemctl disable "$unit" >/dev/null 2>&1 || failed=1
            if sudo systemctl is-enabled --quiet "$unit"; then
                failed=1
            fi
        fi
    fi
    if [[ "$was_active" -eq 1 ]]; then
        if ! sudo systemctl is-active --quiet "$unit"; then
            sudo systemctl start "$unit" >/dev/null 2>&1 || failed=1
        fi
        if [[ "$active_is_transient" -ne 1 ]]; then
            sudo systemctl is-active --quiet "$unit" || failed=1
        fi
    elif sudo systemctl is-active --quiet "$unit"; then
        sudo systemctl stop "$unit" >/dev/null 2>&1 || failed=1
        if sudo systemctl is-active --quiet "$unit"; then
            failed=1
        fi
    fi
    return "$failed"
}

restore_system_state() {
    local failed=0
    [[ "$SYSTEM_STATE_CAPTURED" -eq 1 ]] || return 0
    restore_unit_state knxohui.service "$UI_WAS_ACTIVE" "$UI_WAS_ENABLED" || failed=1
    # A successful Type=oneshot start completes by becoming inactive again.
    restore_unit_state knxohui-backup-cleanup.service "$CLEANUP_SERVICE_WAS_ACTIVE" "" 1 ||
        failed=1
    restore_unit_state knxohui-backup-cleanup.timer "$CLEANUP_TIMER_WAS_ACTIVE" \
        "$CLEANUP_TIMER_WAS_ENABLED" || failed=1
    if [[ "$CURRENT_SWITCHED" -eq 1 && "$UI_WAS_ACTIVE" -eq 1 ]]; then
        sudo systemctl restart knxohui.service >/dev/null 2>&1 || failed=1
        sudo systemctl is-active --quiet knxohui.service || failed=1
    fi
    return "$failed"
}

restore_current_target() {
    local target="$1"
    local restore_link="$BASE/.current.rollback.$$"
    if [[ -e "$restore_link" || -L "$restore_link" ]]; then
        echo "Refusing to reuse rollback link path $restore_link." >&2
        return 1
    fi
    if [[ -n "$target" ]]; then
        if sudo ln -s "$target" "$restore_link" &&
            sudo mv -Tf "$restore_link" "$BASE/current"; then
            return 0
        fi
        sudo rm -f -- "$restore_link" || true
        return 1
    fi
    if ! sudo rm -f -- "$BASE/current"; then
        echo "Could not remove the interrupted current release link: $BASE/current" >&2
        return 1
    fi
    if [[ -e "$BASE/current" || -L "$BASE/current" ]]; then
        echo "The interrupted current release link remains after rollback: $BASE/current" >&2
        return 1
    fi
}

restore_migration_snapshot() {
    local snapshot_dir
    [[ "$MIGRATION_STARTED" -eq 1 ]] || return 0
    [[ -n "$MIGRATION_SNAPSHOT_PATH_FILE" && -f "$MIGRATION_SNAPSHOT_PATH_FILE" ]] || return 0
    [[ -n "$MIGRATION_ROLLBACK_SCRIPT" && -f "$MIGRATION_ROLLBACK_SCRIPT" ]] || return 1
    snapshot_dir="$(cat "$MIGRATION_SNAPSHOT_PATH_FILE")"
    [[ -n "$snapshot_dir" ]] || return 0
    sudo python3 "$MIGRATION_ROLLBACK_SCRIPT" --restore-snapshot "$snapshot_dir"
}

recover_interrupted_transaction() {
    local source_real="$1" state_file="$1/.installer-transaction-state"
    local previous_target current_real="" previous_real="" value
    local -a saved_state=()
    [[ -f "$state_file" ]] || return 1
    mapfile -t saved_state <"$state_file"
    if [[ "${#saved_state[@]}" -ne 6 ]]; then
        echo "Invalid interrupted-install transaction state: $state_file" >&2
        return 2
    fi
    previous_target="${saved_state[0]}"
    for value in "${saved_state[@]:1}"; do
        if [[ "$value" != 0 && "$value" != 1 ]]; then
            echo "Invalid service state in interrupted-install transaction: $state_file" >&2
            return 2
        fi
    done
    if [[ -n "$previous_target" ]]; then
        # Older transactions persisted readlink's relative releases/<version>.
        # The verified parent now runs setup from /, not the install base.
        if [[ "$previous_target" != /* ]]; then
            previous_target="$BASE/$previous_target"
        fi
        previous_real="$(readlink -f -- "$previous_target")" || return 2
        case "$previous_real/" in
            "$BASE/releases/"*) ;;
            *) echo "Recorded previous release is outside $BASE/releases: $previous_real" >&2; return 2 ;;
        esac
        [[ -d "$previous_real" ]] || {
            echo "Recorded previous release is missing: $previous_real" >&2
            return 2
        }
        previous_target="$previous_real"
    fi
    # readlink -f can succeed for a nonexistent final leaf. Absence of current
    # during first-install preparation is distinct from an existing target.
    if [[ -e "$BASE/current" || -L "$BASE/current" ]]; then
        current_real="$(readlink -f -- "$BASE/current")" || return 2
    fi
    if [[ -n "$current_real" && "$current_real" != "$source_real" &&
        "$current_real" != "$previous_real" ]]; then
        echo "Current release changed during interrupted transaction recovery: $current_real" >&2
        return 2
    fi

    CURRENT_TARGET="$previous_target"
    CURRENT_SWITCHED=1
    MIGRATION_SNAPSHOT_PATH_FILE="$source_real/.migration-snapshot-path"
    MIGRATION_ROLLBACK_SCRIPT="$REPO_ROOT/installer/config_migrations.py"
    MIGRATION_STARTED=1
    UI_WAS_ACTIVE="${saved_state[1]}"
    UI_WAS_ENABLED="${saved_state[2]}"
    CLEANUP_SERVICE_WAS_ACTIVE="${saved_state[3]}"
    CLEANUP_TIMER_WAS_ACTIVE="${saved_state[4]}"
    CLEANUP_TIMER_WAS_ENABLED="${saved_state[5]}"
    SYSTEM_STATE_CAPTURED=1

    restore_migration_snapshot || {
        echo "Could not roll back external data from interrupted setup." >&2
        return 1
    }
    restore_current_target "$previous_target" || return 1
    MIGRATION_STARTED=0
    if [[ -n "${KNXOH_BOOTSTRAP_OUTCOME:-}" ]]; then
        if [[ -z "$previous_target" ]]; then
            SYSTEM_STATE_CAPTURED=0
            CURRENT_SWITCHED=0
            sudo rm -rf -- "$source_real" || return 1
            # There is no application pair (or installed recovery unit) to
            # activate. Return without an outcome; the parent must not restore
            # writers, and the EXIT trap must not invent a failed-stage result.
            trap - EXIT
            echo "Interrupted first installation restored; external snapshots retained. Rerun --update." >&2
            return 2
        fi
        RELEASE_DIR="$source_real"
        MIGRATION_SNAPSHOT_PATH_FILE=""
        finish_protected_stage repair "$UI_WAS_ACTIVE" "$UI_WAS_ENABLED" \
            "$CLEANUP_TIMER_WAS_ACTIVE" "$CLEANUP_TIMER_WAS_ENABLED"
        # This is the existing installer transaction's positively selected failed
        # release, not updater candidate cleanup or release pruning. External
        # snapshots are retained. Removing it allows a fresh verified retry.
        sudo rm -rf -- "$source_real" || return 1
        return 0
    fi
    if ! restore_system_state; then
        echo "Could not restore the pre-install service state; retaining recovery data." >&2
        return 1
    fi
    if ! sudo rm -rf -- "$source_real"; then
        echo "Could not remove the rolled-back release: $source_real" >&2
        return 1
    fi
    CURRENT_SWITCHED=0
    if [[ -n "$previous_target" || -f "$BASE/installer/setup.sh" ]]; then
        echo "Interrupted setup was rolled back to $previous_real; rerun --update to retry."
        return 0
    fi
    echo "Interrupted first installation was rolled back; rerun --update to retry." >&2
    return 2
}

cleanup_setup() {
    local setup_status=$?
    local rollback_failed=0
    trap - EXIT
    if [[ "$setup_status" -ne 0 ]]; then
        restore_migration_snapshot || {
            rollback_failed=1
            echo "Failed to restore the pre-migration configuration snapshot." >&2
        }
        if [[ "$CURRENT_SWITCHED" -eq 1 ]]; then
            restore_current_target "$CURRENT_TARGET" || {
                rollback_failed=1
                echo "Failed to restore the previous active release after setup failure." >&2
            }
        fi
        if [[ -n "${KNXOH_BOOTSTRAP_OUTCOME:-}" ]]; then
            if [[ "$rollback_failed" -eq 0 ]]; then
                # Defer even failure-path service restoration until the parent
                # releases the lease required by boot recovery.
                finish_protected_stage failed "$UI_WAS_ACTIVE" "$UI_WAS_ENABLED" \
                    "$CLEANUP_TIMER_WAS_ACTIVE" "$CLEANUP_TIMER_WAS_ENABLED" || true
            else
                mark_installer_blocked ||
                    echo "Could not persist the installer deny marker; manual recovery required." >&2
                echo "Writers remain stopped; administrator recovery is required." >&2
            fi
        else
            restore_system_state ||
                echo "Could not restore the pre-install service state; recovery remains required." >&2
        fi
    fi
    if [[ -n "$STAGING_DIR" ]]; then
        sudo rm -rf -- "$STAGING_DIR" "$CURRENT_LINK_TMP" 2>/dev/null || true
    fi
    return "$setup_status"
}

capture_system_state
trap cleanup_setup EXIT

repair_system_components() {
    local releases_dir="$BASE/releases"
    local source_real current_real temporary_link previous_target=""
    local systemd_changed=0
    local release_activated=0
    local needs_activation=0
    local ui_unit_missing=0 cleanup_timer_missing=0

    if [[ ! -f "$REPO_ROOT/installer/knxohui.service" || ! -f "$REPO_ROOT/installer/launch_web.sh" ]]; then
        echo "The selected application tree is incomplete and cannot be repaired: $REPO_ROOT" >&2
        return 2
    fi
    if [[ -e "$BASE/current" && ! -L "$BASE/current" ]]; then
        echo "Refusing to replace non-symlink path $BASE/current." >&2
        return 2
    fi
    # System components ALWAYS come from this verified administrator payload,
    # never from the candidate/current release. The target remains immutable.
    source_real="$(readlink -f "${KNXOH_REPAIR_TARGET:-$REPO_ROOT}")"
    if [[ -L "$BASE/current" ]]; then
        if [[ ! -e "$BASE/current" ]]; then
            echo "Refusing to repair through broken current symlink $BASE/current." >&2
            return 2
        fi
        previous_target="$(readlink "$BASE/current")"
        CURRENT_TARGET="$previous_target"
        current_real="$(readlink -f "$BASE/current")"
        case "$current_real/" in
            "$releases_dir/"*) ;;
            *) echo "Refusing current symlink outside the release directory: $current_real" >&2; return 2 ;;
        esac
        if [[ "$source_real" != "$current_real" ]]; then
            case "$source_real/" in
                "$releases_dir/"*) ;;
                *) echo "Repair source is not the active release: $REPO_ROOT" >&2; return 2 ;;
            esac
            if [[ "$ACTIVATE_EXISTING" -ne 1 ]]; then
                echo "Refusing to repair from an inactive release without --activate-existing." >&2
                return 2
            fi
            needs_activation=1
            release_activated=1
        fi
    else
        case "$source_real/" in
            "$releases_dir/"*)
                needs_activation=1
                release_activated=1
                ;;
            *)
                if [[ "$source_real" != "$BASE" ]]; then
                    echo "Repair source must be the active release or a release under $releases_dir." >&2
                    return 2
                fi
                ;;
        esac
    fi
    if [[ -f "$source_real/.install-incomplete" ]]; then
        RELEASE_WAS_INCOMPLETE=1
        release_activated=1
        if [[ -f "$source_real/.installer-transaction-state" ]]; then
            recover_interrupted_transaction "$source_real"
            return $?
        fi
    fi
    if [[ ! -f "$PATHS_FILE" ]]; then
        echo "Cannot repair without the existing path contract: $PATHS_FILE" >&2
        return 2
    fi

    # Read-only administrator check, never the existing release's interpreter.
    # Component repair may retain a predecessor venv with explicit guidance;
    # publishing an inactive incompatible tree is refused before provisioning.
    check_repair_release "$source_real" "$needs_activation"

    if ! getent group "$SERVICE_USER" >/dev/null 2>&1; then
        sudo groupadd -r "$SERVICE_USER"
    fi
    if ! id -u "$SERVICE_USER" >/dev/null 2>&1; then
        sudo useradd -r -g "$SERVICE_USER" -s /usr/sbin/nologin "$SERVICE_USER"
    fi
    if ! getent group openhab >/dev/null 2>&1; then
        sudo groupadd openhab
    fi
    sudo usermod -a -G openhab "$SERVICE_USER"

    local unit
    for unit in knxohui.service knxohui-backup-cleanup.service knxohui-backup-cleanup.timer; do
        if [[ ! -e "/etc/systemd/system/$unit" ]]; then
            case "$unit" in
                knxohui.service) ui_unit_missing=1 ;;
                knxohui-backup-cleanup.timer) cleanup_timer_missing=1 ;;
            esac
        fi
    done
    provision_updater
    systemd_changed=1
    if [[ -n "${KNXOH_BOOTSTRAP_OUTCOME:-}" ]]; then
        # Link activation below still belongs to this protected mutation stage.
        systemd_changed=0
    fi
    if [[ "$systemd_changed" -eq 1 ]]; then
        sudo systemctl daemon-reload
    fi
    if [[ "$ui_unit_missing" -eq 1 && -z "${KNXOH_BOOTSTRAP_OUTCOME:-}" ]]; then
        sudo systemctl enable knxohui.service
    fi
    if [[ "$cleanup_timer_missing" -eq 1 && -z "${KNXOH_BOOTSTRAP_OUTCOME:-}" ]]; then
        sudo systemctl enable knxohui-backup-cleanup.timer
    fi
    if [[ "$needs_activation" -eq 1 ]]; then
        temporary_link="$BASE/.current.repair.$$"
        if [[ -e "$temporary_link" || -L "$temporary_link" ]]; then
            echo "Refusing to reuse repair link path $temporary_link." >&2
            return 2
        fi
        if ! sudo ln -s "${source_real#"$BASE"/}" "$temporary_link"; then
            return 1
        fi
        if ! sudo mv -Tf "$temporary_link" "$BASE/current"; then
            sudo rm -f -- "$temporary_link" || true
            return 1
        fi
        CURRENT_SWITCHED=1
    fi
    if [[ -n "${KNXOH_BOOTSTRAP_OUTCOME:-}" ]]; then
        RELEASE_DIR="$source_real"
        local start_ui=0
        if [[ "$ui_unit_missing" -eq 1 || ( "$release_activated" -eq 1 && "$UI_WAS_ACTIVE" -eq 1 ) ]]; then
            start_ui=1
        fi
        if [[ -f "$source_real/.install-incomplete" ]]; then
            sudo rm -f -- "$source_real/.install-incomplete"
        fi
        finish_protected_stage repair "$start_ui" "$ui_unit_missing" \
            "$cleanup_timer_missing" "$cleanup_timer_missing"
        return 0
    fi
    if [[ "$release_activated" -eq 1 ]] && sudo systemctl is-active --quiet knxohui.service; then
        if ! sudo systemctl restart knxohui.service; then
            return 1
        fi
    elif [[ "$ui_unit_missing" -eq 1 ]] && ! sudo systemctl is-active --quiet knxohui.service; then
        if ! sudo systemctl start knxohui.service; then
            return 1
        fi
    fi
    if [[ "$cleanup_timer_missing" -eq 1 ]] &&
        ! sudo systemctl is-active --quiet knxohui-backup-cleanup.timer; then
        if ! sudo systemctl start knxohui-backup-cleanup.timer; then
            return 1
        fi
    fi
    if [[ -f "$source_real/.install-incomplete" ]]; then
        if ! sudo rm -f -- "$source_real/.install-incomplete"; then
            return 1
        fi
    fi
    echo "System component repair complete; user configuration and runtime data were not migrated or rewritten."
}

if [[ "$SETUP_MODE" == "repair" ]]; then
    repair_system_components
    exit $?
fi

RELEASE_VERSION="$(tr -d '\r\n' < "$REPO_ROOT/VERSION")"
python3 - "$REPO_ROOT" "$RELEASE_VERSION" <<'PY'
import sys

sys.path.insert(0, sys.argv[1])
from scripts.build_release import ReleaseArtifactError, validate_semver

try:
    validate_semver(sys.argv[2])
except ReleaseArtifactError as error:
    raise SystemExit(f"Invalid VERSION file: {error}") from error
PY

RELEASES_DIR="$BASE/releases"
RELEASE_DIR="$BASE/releases/$RELEASE_VERSION"
STAGING_DIR="$BASE/releases/.${RELEASE_VERSION}.staging.$$"
CURRENT_LINK_TMP="$BASE/.current.$$"
MIGRATION_SNAPSHOT_PATH_FILE="$RELEASE_DIR/.migration-snapshot-path"
MIGRATION_ROLLBACK_SCRIPT="$RELEASE_DIR/installer/config_migrations.py"
TRANSACTION_STATE_FILE="$RELEASE_DIR/.installer-transaction-state"
TRANSACTION_STATE_STAGING_FILE="$STAGING_DIR/.installer-transaction-state"
CURRENT_TARGET=""
CURRENT_SWITCHED=0
if [[ -e "$RELEASE_DIR" || -L "$RELEASE_DIR" ]]; then
    echo "Release $RELEASE_VERSION already exists at $RELEASE_DIR; refusing to overwrite it." >&2
    exit 2
fi
if [[ -e "$BASE/current" && ! -L "$BASE/current" ]]; then
    echo "Refusing to replace non-symlink path $BASE/current." >&2
    exit 2
fi
if [[ -L "$BASE/current" ]]; then
    if [[ ! -e "$BASE/current" ]]; then
        echo "Refusing to replace broken current symlink $BASE/current." >&2
        exit 2
    fi
    CURRENT_TARGET="$(readlink -f "$BASE/current")"
    case "$CURRENT_TARGET/" in
        "$RELEASES_DIR/"*) ;;
        *)
            echo "Refusing current symlink outside the release directory: $CURRENT_TARGET" >&2
            exit 2
            ;;
    esac
fi
if [[ -e "$STAGING_DIR" || -L "$STAGING_DIR" ]]; then
    echo "Refusing to reuse existing release staging path $STAGING_DIR." >&2
    exit 2
fi

echo "Using application directory: $BASE"
echo "Using configuration directory: $CONFIG_DIR"
echo "Using runtime data directory: $DATA_DIR"
echo "Using backup directory: $BACKUP_DIR"

stop_unit_if_active() {
    local unit="$1"
    if sudo systemctl is-active --quiet "$unit"; then
        sudo systemctl stop "$unit"
    fi
}

if ! getent group "$SERVICE_USER" >/dev/null 2>&1; then
    sudo groupadd -r "$SERVICE_USER"
fi
if ! id -u "$SERVICE_USER" >/dev/null 2>&1; then
    sudo useradd -r -g "$SERVICE_USER" -s /usr/sbin/nologin "$SERVICE_USER"
fi

sudo mkdir -p "$BASE" "$RELEASES_DIR" "$CONFIG_DIR"
sudo chown root:root "$BASE" "$RELEASES_DIR"
sudo chmod 0755 "$BASE" "$RELEASES_DIR"
sudo chown -R root:root "$RELEASES_DIR"
sudo chmod -R go-w "$RELEASES_DIR"
sudo chown root:"$SERVICE_USER" "$CONFIG_DIR"
sudo chmod 0750 "$CONFIG_DIR"

sudo mkdir -p "$STAGING_DIR"

echo "Installing application files while preserving runtime configuration"
sudo rsync -a \
    --exclude .git --exclude .github --exclude .superpowers --exclude tests \
    --exclude .pytest_cache --exclude .venv --exclude venv --exclude var \
    --exclude openhab --exclude test-results --exclude dist --exclude __pycache__ \
    --exclude docs/screenshots --exclude requirements-dev.txt --exclude pytest.ini \
    --exclude .env --exclude secrets.env --exclude '*.knxproj' --exclude '*.knxprojarchive' \
    --exclude '*.tar.gz' --exclude '*.sha256' \
    "$REPO_ROOT/" "$STAGING_DIR/"

if ! getent group openhab >/dev/null 2>&1; then
    sudo groupadd openhab
fi
sudo usermod -a -G openhab "$SERVICE_USER"

transaction_state_temporary="$TRANSACTION_STATE_STAGING_FILE.tmp.$$"
printf '%s\n' \
    "$CURRENT_TARGET" \
    "$UI_WAS_ACTIVE" \
    "$UI_WAS_ENABLED" \
    "$CLEANUP_SERVICE_WAS_ACTIVE" \
    "$CLEANUP_TIMER_WAS_ACTIVE" \
    "$CLEANUP_TIMER_WAS_ENABLED" >"$transaction_state_temporary"
chmod 0600 "$transaction_state_temporary"
sudo mv -Tf "$transaction_state_temporary" "$TRANSACTION_STATE_STAGING_FILE"
sudo touch "$STAGING_DIR/.install-incomplete"
sudo mv "$STAGING_DIR" "$RELEASE_DIR"
TRANSACTION_STATE_FILE="$RELEASE_DIR/.installer-transaction-state"
sudo python3 -m venv --copies "$RELEASE_DIR/venv"
sudo "$RELEASE_DIR/venv/bin/python" -m pip install --upgrade pip
sudo "$RELEASE_DIR/venv/bin/python" -m pip install -r "$REPO_ROOT/requirements.txt"
sudo python3 - "$RELEASE_DIR/venv" <<'PY'
import os
import sys
from pathlib import Path

link = Path(sys.argv[1]) / "lib64"
if link.is_symlink() and os.readlink(link) == "lib":
    link.unlink()
PY
sudo chown -R root:root "$RELEASE_DIR"
sudo chmod -R go-w "$RELEASE_DIR"
echo "Stopping the Web UI and backup cleanup during migration"
stop_unit_if_active knxohui-backup-cleanup.timer
stop_unit_if_active knxohui-backup-cleanup.service
stop_unit_if_active knxohui.service
sudo ln -s "releases/$RELEASE_VERSION" "$CURRENT_LINK_TMP"
sudo mv -Tf "$CURRENT_LINK_TMP" "$BASE/current"
CURRENT_SWITCHED=1
MIGRATION_STARTED=1
echo "Migrating configuration, jobs, staging data and backups"
sudo "$BASE/current/venv/bin/python" "$BASE/current/installer/migrate_runtime_data.py" \
    --source-root "$BASE" \
    --template-root "$BASE/current" \
    --config-dir "$CONFIG_DIR" \
    --data-dir "$DATA_DIR" \
    --backup-dir "$BACKUP_DIR" \
    --install-dir "$BASE" \
    --paths-file "$PATHS_FILE" \
    --defer-legacy-cleanup \
    --snapshot-backup-dir "$CONFIG_DIR/.installer-state" \
    --snapshot-path-file "$MIGRATION_SNAPSHOT_PATH_FILE" \
    --secure-snapshot-root
export KNXOH_INSTALL_DIR="$BASE"
export KNXOH_CONFIG_DIR="$CONFIG_DIR"
export KNXOH_DATA_DIR="$DATA_DIR"
export KNXOH_BACKUP_DIR="$BACKUP_DIR"
export KNXOH_PATHS_FILE="$PATHS_FILE"
echo "Checking the Web UI network binding"
sudo "$RELEASE_DIR/venv/bin/python" "$RELEASE_DIR/installer/configure_bind.py" \
    "$CONFIG_DIR/config.json"
sudo mkdir -p "$DATA_DIR/jobs" "$DATA_DIR/staging" "$DATA_DIR/generated" "$BACKUP_DIR"
sudo chown -R "$SERVICE_USER":"$SERVICE_USER" "$DATA_DIR" "$BACKUP_DIR"
sudo chown root:"$SERVICE_USER" "$CONFIG_DIR" "$PATHS_FILE"
sudo chmod 0750 "$CONFIG_DIR"
sudo chmod 0644 "$PATHS_FILE"
CONF="$CONFIG_DIR/config.json"
echo "Configuring Web UI credentials"
sudo "$RELEASE_DIR/venv/bin/python" "$RELEASE_DIR/installer/configure_auth.py" \
    --config "$CONF" --secrets "$CONFIG_DIR/secrets.env"
sudo chown root:"$SERVICE_USER" "$CONF" "$CONFIG_DIR/secrets.env"
sudo chmod 0640 "$CONF" "$CONFIG_DIR/secrets.env"
echo "Restricting OpenHAB writes to generated output files"
sudo env \
    "KNXOH_INSTALL_DIR=$BASE" \
    "KNXOH_CONFIG_DIR=$CONFIG_DIR" \
    "KNXOH_DATA_DIR=$DATA_DIR" \
    "KNXOH_BACKUP_DIR=$BACKUP_DIR" \
    "KNXOH_PATHS_FILE=$PATHS_FILE" \
    "$RELEASE_DIR/venv/bin/python" "$RELEASE_DIR/installer/provision_managed_files.py" \
    --service-user "$SERVICE_USER" --openhab-group openhab
echo "Provisioning protected updater bundle, launch helpers, policy and units"
provision_updater
PORT=$(python3 - "$CONF" <<'PY'
import json
import sys
with open(sys.argv[1], encoding="utf-8") as config_file:
    print(json.load(config_file).get("port", 8085))
PY
)
if [[ -n "${KNXOH_BOOTSTRAP_OUTCOME:-}" ]]; then
    finish_protected_stage install 1 1 1 1
    exit 0
fi
sudo systemctl daemon-reload
sudo systemctl enable knxohui.service
sudo systemctl restart knxohui.service
if ! sudo systemctl is-active --quiet knxohui.service; then
    echo "The Web UI service did not become healthy after activation." >&2
    exit 1
fi
sudo systemctl enable --now knxohui-backup-cleanup.timer
sudo rm -f -- "$RELEASE_DIR/.install-incomplete"
MIGRATION_STARTED=0
sudo rm -f -- "$MIGRATION_SNAPSHOT_PATH_FILE" "$TRANSACTION_STATE_FILE" || true
if ! sudo "$RELEASE_DIR/venv/bin/python" "$RELEASE_DIR/installer/migrate_runtime_data.py" \
    --source-root "$BASE" \
    --template-root "$RELEASE_DIR" \
    --config-dir "$CONFIG_DIR" \
    --data-dir "$DATA_DIR" \
    --backup-dir "$BACKUP_DIR" \
    --install-dir "$BASE" \
    --paths-file "$PATHS_FILE" \
    --cleanup-legacy \
    --snapshot-backup-dir "$CONFIG_DIR/.installer-state"; then
    echo "Warning: legacy runtime cleanup was deferred; canonical migrated data is active." >&2
fi

echo "Installation complete. Web UI: http://127.0.0.1:$PORT"
