#!/usr/bin/env bash
# Safe KNX to openHAB uninstall. Run as a regular user with sudo privileges.
set -euo pipefail
export LC_ALL=C

SERVICE_USER="knxohui"
PATHS_FILE="${KNXOH_PATHS_FILE:-/etc/knx_to_openhab/paths.env}"
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
            KNXOH_INSTALL_DIR|KNXOH_CONFIG_DIR|KNXOH_DATA_DIR|KNXOH_BACKUP_DIR) ;;
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

has_uninstall_artifacts=0
[[ -e "$INSTALL_DIR" ]] && has_uninstall_artifacts=1
[[ -e "$PATHS_FILE" ]] && has_uninstall_artifacts=1
for path in /usr/local/libexec/knx_to_openhab "${UNIT_FILES[@]}" "${FIXED_FILES[@]}"; do
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

stop_unit_before_removal() {
    local unit="$1" active_state attempt pending_jobs
    local job_id job_unit job_type job_state has_pending_job has_pending_start
    if ! active_state=$(sudo systemctl show --property=ActiveState --value "$unit"); then
        fail "Could not inspect $unit state; no files were removed."
    fi

    case "$active_state" in
        active|activating|deactivating|reloading|inactive|failed|dead)
            if ! sudo systemctl stop "$unit"; then
                fail "Could not stop $unit; no files were removed."
            fi
            ;;
        not-found) return 0 ;;
        *) fail "Unknown $unit state '$active_state'; no files were removed." ;;
    esac

    for ((attempt = 0; attempt < 30; attempt++)); do
        if ! active_state=$(sudo systemctl show --property=ActiveState --value "$unit"); then
            fail "Could not recheck $unit state; no files were removed."
        fi
        case "$active_state" in
            inactive|failed|dead|not-found) ;;
            active|activating|deactivating|reloading)
                sleep 1
                continue
                ;;
            *) fail "Unknown $unit state '$active_state'; no files were removed." ;;
        esac

        if ! pending_jobs=$(sudo systemctl list-jobs --no-legend --no-pager "$unit"); then
            fail "Could not inspect pending jobs for $unit; no files were removed."
        fi
        has_pending_job=0
        has_pending_start=0
        while read -r job_id job_unit job_type job_state; do
            if [[ "$job_unit" == "$unit" ]]; then
                has_pending_job=1
                [[ "$job_type" == stop ]] || has_pending_start=1
            fi
        done <<< "$pending_jobs"
        if (( has_pending_start )); then
            if ! sudo systemctl stop "$unit"; then
                fail "Could not cancel a pending start for $unit; no files were removed."
            fi
        elif (( ! has_pending_job )); then
            return 0
        fi
        sleep 1
    done
    fail "Timed out waiting for $unit to stop; no files were removed."
}

for unit in "${UNITS[@]}"; do
    stop_unit_before_removal "$unit"
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

sudo rm -f -- "${UNIT_FILES[@]}" "${FIXED_FILES[@]}"
sudo rm -rf -- /usr/local/libexec/knx_to_openhab
sudo systemctl daemon-reload
sudo rm --one-file-system -rf -- "$INSTALL_DIR"

if ((PURGE)); then
    sudo rm --one-file-system -rf -- "$CONFIG_DIR" "$DATA_DIR" "$BACKUP_DIR"
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
