#!/usr/bin/env bash
# Safe KNX to openHAB uninstall. Run as a regular user with sudo privileges.
set -euo pipefail
export LC_ALL=C

SERVICE_USER="knxohui"
PATHS_FILE="${KNXOH_PATHS_FILE:-/etc/knx_to_openhab/paths.env}"
export KNXOH_PATHS_FILE="$PATHS_FILE"
DEFAULT_MAINTENANCE_LOCK_FILE="/run/lock/knx_to_openhab/maintenance.lock"
MAINTENANCE_LOCK_HOLDER_PID=""
MAINTENANCE_LOCK_COMMAND_PID=""
UPDATER_LOCK_HOLDER_PID=""
UPDATER_LOCK_COMMAND_PID=""
PURGE=0
YES=0

usage() {
    cat <<'EOF'
Usage: bash uninstall.sh [--purge] [--yes]

Default: remove the application and system integration while preserving
configuration, runtime data, backups, and the knxohui service account.

  --purge  Also remove configured data paths and the service account.
  --yes    Skip the prompt. Required for non-interactive use.
  --help   Show this help.

Interactive purge requires typing PURGE unless --yes is supplied.
EOF
}

fail() {
    printf '[ERROR] %s\n' "$1" >&2
    exit 2
}

while (($#)); do
    case "$1" in
        --purge) PURGE=1 ;;
        --yes) YES=1 ;;
        --help|-h) usage; exit 0 ;;
        *) fail "Unknown option: $1" ;;
    esac
    shift
done

if [[ "$EUID" -eq 0 && "${ALLOW_ROOT:-0}" != "1" ]]; then
    fail "Run as a regular user with sudo privileges; do not run this script as root."
fi
command -v sudo >/dev/null 2>&1 || fail "sudo is required."

decode_saved_value() {
    local raw="$1" body="" character next index
    DECODED_VALUE=""
    if [[ "$raw" == \"* ]]; then
        ((${#raw} >= 2)) && [[ "${raw: -1}" == '"' ]] || return 1
        body="${raw:1:${#raw}-2}"
        for ((index = 0; index < ${#body}; index++)); do
            character="${body:index:1}"
            if [[ "$character" == \\ ]]; then
                ((index + 1 < ${#body})) || return 1
                ((index += 1))
                next="${body:index:1}"
                [[ "$next" == \\ || "$next" == '"' ]] || return 1
                DECODED_VALUE+="$next"
            else
                [[ "$character" != '"' ]] || return 1
                DECODED_VALUE+="$character"
            fi
        done
    else
        # Older files may contain a plain path. It is still data: never evaluate it.
        DECODED_VALUE="$raw"
    fi
    [[ -n "$DECODED_VALUE" && "$DECODED_VALUE" != *$'\r'* ]] || return 1
}

declare -A SAVED_PATHS=()
if [[ -e "$PATHS_FILE" || -L "$PATHS_FILE" ]]; then
    [[ -f "$PATHS_FILE" && ! -L "$PATHS_FILE" ]] || fail "Path registry is not a regular file: $PATHS_FILE"
    while IFS= read -r line || [[ -n "$line" ]]; do
        line="${line%$'\r'}"
        trimmed="${line#"${line%%[![:space:]]*}"}"
        [[ -n "$trimmed" && "$trimmed" != \#* ]] || continue
        [[ "$trimmed" == *=* ]] || continue
        key="${trimmed%%=*}"
        value="${trimmed#*=}"
        case "$key" in
            KNXOH_INSTALL_DIR|KNXOH_CONFIG_DIR|KNXOH_DATA_DIR|KNXOH_BACKUP_DIR|KNXOH_MAINTENANCE_LOCK_FILE) ;;
            *) continue ;;
        esac
        [[ ! -v "SAVED_PATHS[$key]" ]] || fail "Duplicate path entry in $PATHS_FILE: $key"
        decode_saved_value "$value" || fail "Invalid path value in $PATHS_FILE: $key"
        SAVED_PATHS[$key]="$DECODED_VALUE"
    done < "$PATHS_FILE"
fi

select_path() {
    local key="$1" fallback="$2"
    if [[ -v "$key" ]]; then
        printf '%s' "${!key}"
    elif [[ -v "SAVED_PATHS[$key]" ]]; then
        printf '%s' "${SAVED_PATHS[$key]}"
    else
        printf '%s' "$fallback"
    fi
}

SAVED_MAINTENANCE_LOCK_FILE="${SAVED_PATHS[KNXOH_MAINTENANCE_LOCK_FILE]:-}"
if [[ -n "${KNXOH_MAINTENANCE_LOCK_FILE:-}" && \
    -n "$SAVED_MAINTENANCE_LOCK_FILE" && \
    "$KNXOH_MAINTENANCE_LOCK_FILE" != "$SAVED_MAINTENANCE_LOCK_FILE" ]]; then
    fail "The configured maintenance lock path cannot change during uninstall."
fi
KNXOH_MAINTENANCE_LOCK_FILE="$(select_path KNXOH_MAINTENANCE_LOCK_FILE "$DEFAULT_MAINTENANCE_LOCK_FILE")"
if [[ "$KNXOH_MAINTENANCE_LOCK_FILE" != /* || "$KNXOH_MAINTENANCE_LOCK_FILE" == / || \
    "$KNXOH_MAINTENANCE_LOCK_FILE" == */ || "$KNXOH_MAINTENANCE_LOCK_FILE" == *$'\n'* || \
    "$KNXOH_MAINTENANCE_LOCK_FILE" == *$'\r'* ]]; then
    fail "The maintenance lock path is not a safe absolute file path."
fi
case "/$KNXOH_MAINTENANCE_LOCK_FILE/" in
    */./*|*/../*) fail "The maintenance lock path has an unsafe component." ;;
esac
export KNXOH_MAINTENANCE_LOCK_FILE

INSTALL_DIR="$(select_path KNXOH_INSTALL_DIR /opt/knx_to_openhab)"
CONFIG_DIR="$(select_path KNXOH_CONFIG_DIR /etc/knx_to_openhab)"
DATA_DIR="$(select_path KNXOH_DATA_DIR /var/lib/knx_to_openhab)"
BACKUP_DIR="$(select_path KNXOH_BACKUP_DIR /var/backups/knx_to_openhab)"

path_has_symlink_component() {
    local path="$1" current="" component
    local -a components=()
    IFS='/' read -r -a components <<< "${path#/}"
    for component in "${components[@]}"; do
        [[ -n "$component" && "$component" != . && "$component" != .. ]] || return 0
        current+="/$component"
        [[ ! -L "$current" ]] || return 0
    done
    return 1
}

is_forbidden_root() {
    local candidate="$1" root
    local -a roots=(
        / /bin /boot /dev /etc /home /lib /lib64 /lost+found /media /mnt /opt
        /proc /root /run /sbin /srv /sys /tmp /usr /var /var/lib /var/backups
        /usr/local
    )
    for root in "${roots[@]}"; do
        [[ "$candidate" != "$root" ]] || return 0
    done
    return 1
}

normalize_and_validate_path() {
    local label="$1" raw="$2" normalized component
    [[ "$raw" == /* ]] || fail "$label path must be absolute: $raw"
    [[ "$raw" != *$'\n'* && "$raw" != *$'\r'* ]] || fail "$label path contains a control character."
    [[ "$raw" != */ ]] || fail "$label path must not end with '/': $raw"
    local -a path_parts=()
    IFS='/' read -r -a path_parts <<< "${raw#/}"
    for component in "${path_parts[@]}"; do
        [[ -n "$component" && "$component" != . && "$component" != .. ]] || fail "$label path has an unsafe component: $raw"
    done
    path_has_symlink_component "$raw" && fail "$label path contains a symlink: $raw"
    normalized="$(realpath -m -- "$raw")" || fail "Could not normalize $label path: $raw"
    is_forbidden_root "$normalized" && fail "Refusing a broad system directory as $label: $normalized"
    printf '%s' "$normalized"
}

INSTALL_DIR="$(normalize_and_validate_path 'Application' "$INSTALL_DIR")"
CONFIG_DIR="$(normalize_and_validate_path 'Configuration' "$CONFIG_DIR")"
DATA_DIR="$(normalize_and_validate_path 'Runtime data' "$DATA_DIR")"
BACKUP_DIR="$(normalize_and_validate_path 'Backups' "$BACKUP_DIR")"

path_contains() {
    local parent="$1" candidate="$2"
    [[ "$candidate" == "$parent" || "$candidate" == "$parent/"* ]]
}

validate_separate_paths() {
    local -a names=(Application Configuration 'Runtime data' Backups)
    local -a paths=("$INSTALL_DIR" "$CONFIG_DIR" "$DATA_DIR" "$BACKUP_DIR")
    local left right i j
    for ((i = 0; i < ${#paths[@]}; i++)); do
        for ((j = i + 1; j < ${#paths[@]}; j++)); do
            left="${paths[i]}"
            right="${paths[j]}"
            if path_contains "$left" "$right" || path_contains "$right" "$left"; then
                fail "${names[i]} and ${names[j]} paths overlap: $left, $right"
            fi
        done
    done
}
validate_separate_paths

validate_application_directory() {
    if [[ -e "$INSTALL_DIR" ]]; then
        [[ -d "$INSTALL_DIR" && ! -L "$INSTALL_DIR" ]] || fail "Application path is not a real directory: $INSTALL_DIR"
        if [[ ! -d "$INSTALL_DIR/installer" && ! -e "$INSTALL_DIR/install.sh" \
            && ! -e "$INSTALL_DIR/knxproject_to_openhab.py" && ! -e "$INSTALL_DIR/.git" \
            && ! -e "$INSTALL_DIR/current" ]]; then
            fail "Application path does not look like a KNX to openHAB installation; refusing to remove it: $INSTALL_DIR"
        fi
        for legacy_path in \
            "$INSTALL_DIR/var/lib/knx_to_openhab" \
            "$INSTALL_DIR/var/backups/knx_to_openhab"; do
            if [[ -e "$legacy_path" ]]; then
                fail "Legacy runtime data remains inside the application tree ($legacy_path). Run the current setup migration first; no data was removed."
            fi
        done
        if command -v mountpoint >/dev/null 2>&1 && mountpoint -q -- "$INSTALL_DIR"; then
            fail "Application path is a mount point; refusing to remove it: $INSTALL_DIR"
        fi
    fi
}

validate_user_data_directories() {
    local label path index
    local -a names=(Configuration "Runtime data" Backups)
    local -a paths=("$CONFIG_DIR" "$DATA_DIR" "$BACKUP_DIR")
    for ((index = 0; index < ${#paths[@]}; index++)); do
        label="${names[index]}"
        path="${paths[index]}"
        if [[ -e "$path" ]]; then
            [[ -d "$path" && ! -L "$path" ]] || fail "$label path is not a directory: $path"
            if command -v mountpoint >/dev/null 2>&1 && mountpoint -q -- "$path"; then
                fail "$label path is a mount point; refusing to remove it: $path"
            fi
        fi
    done
}

validate_application_directory
validate_user_data_directories

UNITS=(
    knxohui.service
    knxohui-update.service
    knxohui-backup-cleanup.service
    knxohui-backup-cleanup.timer
)
UNIT_FILES=(
    /etc/systemd/system/knxohui-update.service
    /etc/systemd/system/knxohui.service
    /etc/systemd/system/knxohui-backup-cleanup.service
    /etc/systemd/system/knxohui-backup-cleanup.timer
)
FIXED_FILES=(
    /etc/sudoers.d/knxohui
    /usr/local/sbin/knxohui-service-update
)
TMPFILES_CONFIG="/etc/tmpfiles.d/knx_to_openhab.conf"

has_uninstall_artifacts=0
[[ -e "$INSTALL_DIR" ]] && has_uninstall_artifacts=1
[[ -e "$PATHS_FILE" ]] && has_uninstall_artifacts=1
for path in /usr/local/libexec/knx_to_openhab "$TMPFILES_CONFIG" \
    "${UNIT_FILES[@]}" "${FIXED_FILES[@]}"; do
    [[ ! -e "$path" && ! -L "$path" ]] || has_uninstall_artifacts=1
done
if (( ! has_uninstall_artifacts )); then
    printf '[OK] Anwendung und Systemintegration sind bereits entfernt; keine Nutzerdaten wurden verändert.\n'
    exit 0
fi

show_target() {
    local path="$1"
    if [[ -e "$path" || -L "$path" ]]; then
        printf '  [vorhanden] %s\n' "$path"
    else
        printf '  [fehlt]     %s\n' "$path"
    fi
}

printf 'Diese Deinstallation entfernt folgende Anwendungskomponenten:\n'
show_target "$INSTALL_DIR"
show_target /usr/local/libexec/knx_to_openhab
show_target "$TMPFILES_CONFIG"
for path in "${UNIT_FILES[@]}" "${FIXED_FILES[@]}"; do show_target "$path"; done
printf '  systemd-Dienste: %s\n' "${UNITS[*]}"
if ((PURGE)); then
    printf '\nPurge löscht zusätzlich die folgenden Nutzerdaten und das Dienstkonto:\n'
    show_target "$CONFIG_DIR"
    show_target "$DATA_DIR"
    show_target "$BACKUP_DIR"
    printf '  Dienstkonto und Gruppe: %s\n' "$SERVICE_USER"
else
    printf '\nErhalten bleiben Konfiguration, Laufzeitdaten, Backups sowie Dienstkonto und Gruppe:\n'
    printf '  %s\n  %s\n  %s\n  %s\n' "$CONFIG_DIR" "$DATA_DIR" "$BACKUP_DIR" "$SERVICE_USER"
fi

if ((PURGE)) && [[ -t 0 ]]; then
    printf '\nZum vollständigen Löschen exakt PURGE eingeben: '
    expected="PURGE"
    IFS= read -r answer || answer=""
    [[ "$answer" == "$expected" ]] || fail "Bestätigung stimmt nicht überein. Keine Systemänderungen wurden vorgenommen."
elif ((PURGE)) && (( ! YES )); then
    fail "Non-interactive purge requires --purge --yes. No system changes were made."
elif (( ! PURGE )) && (( ! YES )); then
    [[ -t 0 ]] || fail "Non-interactive use requires --yes. No system changes were made."
    printf '\nZum Fortfahren UNINSTALL eingeben: '
    IFS= read -r answer || answer=""
    [[ "$answer" == "UNINSTALL" ]] || fail "Bestätigung stimmt nicht überein. Keine Systemänderungen wurden vorgenommen."
fi

# Paths may have changed while an interactive confirmation was open.
INSTALL_DIR="$(normalize_and_validate_path 'Application' "$INSTALL_DIR")"
CONFIG_DIR="$(normalize_and_validate_path 'Configuration' "$CONFIG_DIR")"
DATA_DIR="$(normalize_and_validate_path 'Runtime data' "$DATA_DIR")"
BACKUP_DIR="$(normalize_and_validate_path 'Backups' "$BACKUP_DIR")"
validate_separate_paths
validate_application_directory
validate_user_data_directories

if [[ -n "${BASH_SOURCE[0]:-}" && -f "${BASH_SOURCE[0]}" ]]; then
    UNINSTALLER_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
else
    UNINSTALLER_DIR=""
fi
STABLE_HELPER_DIR="/usr/local/libexec/knx_to_openhab"
MAINTENANCE_LOCK_HELPER="$STABLE_HELPER_DIR/maintenance_lock.sh"
QUIESCE_SYSTEMD_HELPER="$STABLE_HELPER_DIR/quiesce_systemd_unit.sh"
UNIT_REMOVAL_HELPER="$STABLE_HELPER_DIR/uninstall_unit_files.sh"
UPDATER_LOCK_HOLDER="$STABLE_HELPER_DIR/hold_updater_locks.sh"
if [[ -n "$UNINSTALLER_DIR" ]]; then
    [[ -f "$MAINTENANCE_LOCK_HELPER" ]] || \
        MAINTENANCE_LOCK_HELPER="$UNINSTALLER_DIR/installer/maintenance_lock.sh"
    [[ -f "$QUIESCE_SYSTEMD_HELPER" ]] || \
        QUIESCE_SYSTEMD_HELPER="$UNINSTALLER_DIR/installer/quiesce_systemd_unit.sh"
    [[ -f "$UNIT_REMOVAL_HELPER" ]] || \
        UNIT_REMOVAL_HELPER="$UNINSTALLER_DIR/installer/uninstall_unit_files.sh"
    [[ -f "$UPDATER_LOCK_HOLDER" ]] || \
        UPDATER_LOCK_HOLDER="$UNINSTALLER_DIR/installer/hold_updater_locks.sh"
fi
for helper in "$MAINTENANCE_LOCK_HELPER" "$QUIESCE_SYSTEMD_HELPER" \
    "$UNIT_REMOVAL_HELPER" "$UPDATER_LOCK_HOLDER"; do
    [[ -f "$helper" && ! -L "$helper" ]] || \
        fail "Required uninstall coordination helper is missing: $helper. Run the current setup first."
done
source "$MAINTENANCE_LOCK_HELPER"
source "$UNIT_REMOVAL_HELPER"

resolve_maintenance_lock_path "$PATHS_FILE" || \
    fail "The configured maintenance lock path could not be resolved safely."

if ! validate_maintenance_lock_location \
    "$SERVICE_USER" "$INSTALL_DIR" "$CONFIG_DIR" "$DATA_DIR" "$BACKUP_DIR"; then
    fail "The configured maintenance lock path is unsafe."
fi

if [[ -L "$KNXOH_MAINTENANCE_LOCK_FILE" || \
    ( -e "$KNXOH_MAINTENANCE_LOCK_FILE" && ! -f "$KNXOH_MAINTENANCE_LOCK_FILE" ) ]]; then
    fail "Maintenance lock path is missing or unsafe: $KNXOH_MAINTENANCE_LOCK_FILE"
fi
if [[ ! -e "$KNXOH_MAINTENANCE_LOCK_FILE" ]]; then
    [[ "$KNXOH_MAINTENANCE_LOCK_FILE" == "$DEFAULT_MAINTENANCE_LOCK_FILE" ]] || \
        fail "Custom maintenance lock file does not exist: $KNXOH_MAINTENANCE_LOCK_FILE"
    LOCK_GROUP="$SERVICE_USER"
    if ! getent group "$LOCK_GROUP" >/dev/null 2>&1; then
        LOCK_GROUP=root
    fi
    sudo env "KNXOH_MAINTENANCE_LOCK_FILE=$KNXOH_MAINTENANCE_LOCK_FILE" \
        bash -c 'source "$1"; ensure_maintenance_lock "$2"' \
        _ "$MAINTENANCE_LOCK_HELPER" "$LOCK_GROUP"
fi

quiesce_uninstall_units() {
    sudo bash "$QUIESCE_SYSTEMD_HELPER" knxohui-backup-cleanup.timer || return
    sudo bash "$QUIESCE_SYSTEMD_HELPER" knxohui-backup-cleanup.service || return
    sudo bash "$QUIESCE_SYSTEMD_HELPER" knxohui.service || return
    sudo bash "$QUIESCE_SYSTEMD_HELPER" knxohui-update.service || return
    sudo bash "$QUIESCE_SYSTEMD_HELPER" knxohui-backup-cleanup.timer || return
    sudo bash "$QUIESCE_SYSTEMD_HELPER" knxohui-backup-cleanup.service || return
    sudo bash "$QUIESCE_SYSTEMD_HELPER" knxohui.service
}

release_uninstall_maintenance_lock() {
    local exit_status=$?
    trap - EXIT
    if [[ "$UPDATER_LOCK_COMMAND_PID" =~ ^[0-9]+$ ]]; then
        sudo kill -TERM "$UPDATER_LOCK_COMMAND_PID" >/dev/null 2>&1 || true
    fi
    if [[ "$UPDATER_LOCK_HOLDER_PID" =~ ^[0-9]+$ ]]; then
        kill -TERM "$UPDATER_LOCK_HOLDER_PID" >/dev/null 2>&1 || true
        wait "$UPDATER_LOCK_HOLDER_PID" 2>/dev/null || true
        UPDATER_LOCK_HOLDER_PID=""
    fi
    UPDATER_LOCK_COMMAND_PID=""
    if [[ "$MAINTENANCE_LOCK_COMMAND_PID" =~ ^[0-9]+$ ]]; then
        sudo kill -TERM "$MAINTENANCE_LOCK_COMMAND_PID" >/dev/null 2>&1 || true
    fi
    if [[ -n "$MAINTENANCE_LOCK_HOLDER_PID" ]]; then
        kill -TERM "$MAINTENANCE_LOCK_HOLDER_PID" >/dev/null 2>&1 || true
        wait "$MAINTENANCE_LOCK_HOLDER_PID" 2>/dev/null || true
        MAINTENANCE_LOCK_HOLDER_PID=""
    fi
    MAINTENANCE_LOCK_COMMAND_PID=""
    exit "$exit_status"
}

acquire_uninstall_updater_lock() {
    local timeout_seconds="${KNXOH_UNINSTALL_UPDATER_TIMEOUT_SECONDS:-900}"
    local start_seconds=$SECONDS lock_status read_status ready_fd ready_message command_pid

    if [[ ! -d "$DATA_DIR" ]]; then
        return 0
    fi
    if [[ ! "$timeout_seconds" =~ ^[0-9]+$ ]]; then
        fail "The uninstall updater-lock timeout must be a non-negative integer."
    fi

    while :; do
        coproc UNINSTALL_UPDATER_LOCK_HOLDER {
            exec sudo -u "$SERVICE_USER" bash "$UPDATER_LOCK_HOLDER" "$DATA_DIR/updater.lock"
        }
        UPDATER_LOCK_HOLDER_PID=$UNINSTALL_UPDATER_LOCK_HOLDER_PID
        ready_fd="${UNINSTALL_UPDATER_LOCK_HOLDER[0]}"
        if IFS= read -r -t 2 ready_message <&"$ready_fd"; then
            read_status=0
        else
            read_status=$?
        fi
        if (( read_status == 0 )) && [[ "$ready_message" =~ ^LOCKED\ ([0-9]+)$ ]]; then
            command_pid="${BASH_REMATCH[1]}"
            UPDATER_LOCK_COMMAND_PID="$command_pid"
            exec {ready_fd}<&-
            return 0
        fi
        exec {ready_fd}<&-
        if (( read_status > 128 )); then
            kill -TERM "$UPDATER_LOCK_HOLDER_PID" >/dev/null 2>&1 || true
            wait "$UPDATER_LOCK_HOLDER_PID" 2>/dev/null || true
            UPDATER_LOCK_HOLDER_PID=""
            fail "Timed out waiting for the uninstall updater-lock holder to confirm ownership."
        fi
        if wait "$UPDATER_LOCK_HOLDER_PID"; then
            lock_status=0
        else
            lock_status=$?
        fi
        UPDATER_LOCK_HOLDER_PID=""
        if (( lock_status != 75 )); then
            fail "Could not acquire the uninstall updater lock (flock status $lock_status)."
        fi
        if (( SECONDS - start_seconds >= timeout_seconds )); then
            fail "Timed out waiting for the uninstall updater lock."
        fi
        sleep 1
    done
}

acquire_uninstall_maintenance_lock() {
    local timeout_seconds="${KNXOH_UNINSTALL_MAINTENANCE_TIMEOUT_SECONDS:-900}"
    local start_seconds=$SECONDS lock_status read_status ready_fd ready_message command_pid
    if [[ ! "$timeout_seconds" =~ ^[0-9]+$ ]]; then
        fail "The uninstall maintenance timeout must be a non-negative integer."
    fi

    while :; do
        quiesce_uninstall_units || fail "Could not quiesce systemd services; no files were removed."
        coproc UNINSTALL_LOCK_HOLDER {
            exec sudo flock --exclusive --nonblock --conflict-exit-code 75 --no-fork \
                "$KNXOH_MAINTENANCE_LOCK_FILE" \
                bash -c 'printf "LOCKED %s\\n" "$$"; exec sleep infinity'
        }
        MAINTENANCE_LOCK_HOLDER_PID=$UNINSTALL_LOCK_HOLDER_PID
        ready_fd="${UNINSTALL_LOCK_HOLDER[0]}"
        if IFS= read -r -t 2 ready_message <&"$ready_fd"; then
            read_status=0
        else
            read_status=$?
        fi
        if (( read_status == 0 )) && [[ "$ready_message" =~ ^LOCKED\ ([0-9]+)$ ]]; then
            command_pid="${BASH_REMATCH[1]}"
            MAINTENANCE_LOCK_COMMAND_PID="$command_pid"
            exec {ready_fd}<&-
            if quiesce_uninstall_units; then
                return 0
            fi
            sudo kill -TERM "$MAINTENANCE_LOCK_COMMAND_PID" >/dev/null 2>&1 || true
            kill -TERM "$MAINTENANCE_LOCK_HOLDER_PID" >/dev/null 2>&1 || true
            wait "$MAINTENANCE_LOCK_HOLDER_PID" 2>/dev/null || true
            MAINTENANCE_LOCK_HOLDER_PID=""
            MAINTENANCE_LOCK_COMMAND_PID=""
            fail "Systemd services did not remain quiescent after acquiring the uninstall lock."
        fi
        exec {ready_fd}<&-
        if (( read_status > 128 )); then
            kill -TERM "$MAINTENANCE_LOCK_HOLDER_PID" >/dev/null 2>&1 || true
            wait "$MAINTENANCE_LOCK_HOLDER_PID" 2>/dev/null || true
            MAINTENANCE_LOCK_HOLDER_PID=""
            fail "Timed out waiting for the uninstall lock holder to confirm exclusive ownership."
        fi
        if wait "$MAINTENANCE_LOCK_HOLDER_PID"; then
            lock_status=0
        else
            lock_status=$?
        fi
        MAINTENANCE_LOCK_HOLDER_PID=""
        if (( lock_status != 75 )); then
            fail "Could not acquire the uninstall maintenance lock (flock status $lock_status)."
        fi
        if (( SECONDS - start_seconds >= timeout_seconds )); then
            fail "Timed out waiting for the uninstall maintenance lock."
        fi
        sleep 1
    done
}

trap release_uninstall_maintenance_lock EXIT
acquire_uninstall_maintenance_lock
acquire_uninstall_updater_lock

if (( PURGE )) && [[ "$KNXOH_MAINTENANCE_LOCK_FILE" == "$DEFAULT_MAINTENANCE_LOCK_FILE" ]]; then
    DEFAULT_LOCK_PARENT="$(dirname -- "$DEFAULT_MAINTENANCE_LOCK_FILE")"
    command -v mountpoint >/dev/null 2>&1 || \
        fail "Cannot safely purge the default maintenance lock without mountpoint."
    if mountpoint -q -- "$DEFAULT_LOCK_PARENT"; then
        fail "Refusing to purge the default maintenance lock parent because it is a mount point: $DEFAULT_LOCK_PARENT"
    else
        mountpoint_status=$?
    fi
    (( mountpoint_status == 32 )) || \
        fail "Could not determine whether the default maintenance lock parent is a mount point: $DEFAULT_LOCK_PARENT"
fi

for unit in "${UNITS[@]}"; do
    if sudo systemctl is-enabled --quiet "$unit"; then
        sudo systemctl disable "$unit"
    else
        status=$?
        case "$status" in
            1|2|3|4|5|6|8) ;;
            *) fail "Could not inspect enablement for $unit (systemctl is-enabled exited $status); no files were removed." ;;
        esac
    fi
done

for unit_file in "${UNIT_FILES[@]}"; do
    remove_unit_file_preserving_mask "$unit_file" || \
        fail "Could not safely remove systemd unit file: $unit_file"
done
remove_unit_file_preserving_mask "$TMPFILES_CONFIG" || \
    fail "Could not safely remove systemd tmpfiles configuration: $TMPFILES_CONFIG"
sudo rm -f -- "${FIXED_FILES[@]}"
sudo rm -rf -- /usr/local/libexec/knx_to_openhab
sudo systemctl daemon-reload
sudo rm --one-file-system -rf -- "$INSTALL_DIR"

if ((PURGE)); then
    sudo rm --one-file-system -rf -- "$CONFIG_DIR" "$DATA_DIR" "$BACKUP_DIR"
    if [[ "$KNXOH_MAINTENANCE_LOCK_FILE" == "$DEFAULT_MAINTENANCE_LOCK_FILE" ]]; then
        sudo rm --one-file-system -rf -- "$(dirname -- "$DEFAULT_MAINTENANCE_LOCK_FILE")"
    fi
    if command -v getent >/dev/null 2>&1 && getent passwd "$SERVICE_USER" >/dev/null; then
        sudo userdel -- "$SERVICE_USER"
    fi
    if command -v getent >/dev/null 2>&1 && getent group "$SERVICE_USER" >/dev/null; then
        sudo groupdel -- "$SERVICE_USER"
    fi
    printf '\n[OK] Anwendung, Systemintegration, Konfiguration, Laufzeitdaten und Backups wurden entfernt.\n'
else
    printf '\n[OK] Anwendung und Systemintegration wurden entfernt. Konfiguration, Laufzeitdaten, Backups und Dienstkonto bleiben erhalten.\n'
    printf '     Erhalten: %s\n     Erhalten: %s\n     Erhalten: %s\n' "$CONFIG_DIR" "$DATA_DIR" "$BACKUP_DIR"
fi
