#!/usr/bin/env bash

setup_systemd_unit_load_state() {
    local unit="${1:-}" load_state

    if [[ -z "$unit" || "$unit" == -* || "$unit" != *.service && "$unit" != *.timer ]]; then
        echo "ERROR: A service or timer unit name is required." >&2
        return 2
    fi
    if ! load_state=$(sudo systemctl show --property=LoadState --value "$unit"); then
        echo "ERROR: Could not inspect the load state for $unit." >&2
        return 1
    fi
    case "$load_state" in
        loaded|masked|not-found) printf '%s\n' "$load_state" ;;
        *)
            echo "ERROR: Unknown load state for $unit: $load_state" >&2
            return 1
            ;;
    esac
}

setup_systemd_unit_is_managed() {
    local unit="$1" destination="$2"
    if grep -Fxq '# Managed by knx_to_openhab installer' "$destination"; then
        return 0
    fi
    # Older releases did not mark their units. Recognize only their known
    # descriptions and launch commands so that repair remains possible.
    case "$unit" in
        knxohui.service)
            grep -Fxq 'Description=KNX to OpenHAB Web UI Service' "$destination" &&
                grep -Fxq 'User=knxohui' "$destination" &&
                grep -Fxq 'Group=knxohui' "$destination" &&
                grep -Eq '^ExecStart=(/usr/local/libexec/knx_to_openhab/launch_web\.sh|/[^[:space:]]*/venv/bin/gunicorn .*web_ui\.backend\.app:app)$' "$destination"
            ;;
        knxohui-update.service)
            grep -Fxq 'Description=KNX to OpenHAB Transactional Updater' "$destination" &&
                grep -Fxq 'User=knxohui' "$destination" &&
                grep -Fxq 'Group=knxohui' "$destination" &&
                grep -Fxq 'ExecStart=/usr/local/libexec/knx_to_openhab/launch_update.sh' "$destination"
            ;;
        knxohui-backup-cleanup.service)
            grep -Fxq 'Description=KNX to OpenHAB Backup Cleanup' "$destination" &&
                grep -Fxq 'User=knxohui' "$destination" &&
                grep -Fxq 'Group=knxohui' "$destination" &&
                grep -Eq '^ExecStart=(/usr/local/libexec/knx_to_openhab/launch_backup_cleanup\.sh|/[^[:space:]]*/installer/backup_cleanup\.sh)$' "$destination"
            ;;
        knxohui-backup-cleanup.timer)
            grep -Fxq 'Description=KNX to OpenHAB Daily Backup Cleanup Timer' "$destination" &&
                grep -Fxq 'Unit=knxohui-backup-cleanup.service' "$destination" &&
                grep -Fxq 'Documentation=https://github.com/diddip21/knx_to_openhab' "$destination"
            ;;
        *) return 1 ;;
    esac
}

preflight_setup_systemd_unit() {
    local unit="$1" destination="$2" load_state fragment
    if ! load_state=$(setup_systemd_unit_load_state "$unit"); then
        return 1
    fi
    if [[ "$load_state" == masked ]]; then
        return 0
    fi
    if [[ "$load_state" == loaded ]]; then
        if ! fragment=$(sudo systemctl show --property=FragmentPath --value "$unit"); then
            echo "ERROR: Could not inspect the unit file for $unit." >&2
            return 1
        fi
        if [[ "$fragment" != "$destination" ]]; then
            echo "ERROR: Refusing to replace a unit outside the managed location: $unit ($fragment)." >&2
            return 1
        fi
    fi
    if [[ -e "$destination" || -L "$destination" ]]; then
        if [[ -L "$destination" || ! -f "$destination" ]] ||
            ! setup_systemd_unit_is_managed "$unit" "$destination"; then
            echo "ERROR: Refusing to replace an unrecognized systemd unit: $destination" >&2
            return 1
        fi
    fi
}

install_setup_systemd_unit() {
    local source_unit="${1:-}" destination="${2:-}" unit="${3:-}"
    local paths_file="${4:-/etc/knx_to_openhab/paths.env}"
    local rendered_source="" install_status

    if [[ -z "$source_unit" || -z "$destination" || ! -f "$source_unit" ]]; then
        echo "ERROR: A unit source and destination are required." >&2
        return 2
    fi
    if grep -Fq 'EnvironmentFile=/etc/knx_to_openhab/paths.env' "$source_unit"; then
        rendered_source="$(mktemp)" || return 1
        if ! python3 - "$source_unit" "$paths_file" >"$rendered_source" <<'PY'
import sys
from pathlib import Path

source, configured_paths_file = map(Path, sys.argv[1:])
value = str(configured_paths_file)
if (
    not configured_paths_file.is_absolute()
    or any(ord(character) < 32 or ord(character) == 127 for character in value)
):
    raise SystemExit("The systemd paths file must be an absolute path without control characters")

safe_bytes = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789/_-.:"
escaped = "".join(
    "%%"
    if byte == ord("%")
    else chr(byte)
    if byte in safe_bytes
    else f"\\x{byte:02x}"
    for byte in value.encode("utf-8")
)
contents = source.read_text(encoding="utf-8")
original = "EnvironmentFile=/etc/knx_to_openhab/paths.env"
if contents.count(original) != 1:
    raise SystemExit(f"Expected one managed paths-file directive in {source}")
sys.stdout.write(contents.replace(original, f"EnvironmentFile={escaped}"))
PY
        then
            rm -f -- "$rendered_source"
            return 1
        fi
        source_unit="$rendered_source"
    fi
    if ! preflight_setup_systemd_unit "$unit" "$destination"; then
        [[ -z "$rendered_source" ]] || rm -f -- "$rendered_source"
        return 1
    fi
    if ! load_state=$(setup_systemd_unit_load_state "$unit"); then
        [[ -z "$rendered_source" ]] || rm -f -- "$rendered_source"
        return 1
    fi
    if [[ "$load_state" == masked ]]; then
        printf 'Preserving the administrator-masked unit: %s\n' "$unit"
        [[ -z "$rendered_source" ]] || rm -f -- "$rendered_source"
        return 0
    fi
    if sudo install -m 0644 -- "$source_unit" "$destination"; then
        install_status=0
    else
        install_status=$?
    fi
    [[ -z "$rendered_source" ]] || rm -f -- "$rendered_source"
    return "$install_status"
}

setup_systemctl_if_unmasked() {
    local unit="${1:-}" load_state
    shift || true
    if (($# == 0)); then
        echo "ERROR: A systemctl action is required for $unit." >&2
        return 2
    fi
    case "$1" in
        enable|restart|start) ;;
        *)
            echo "ERROR: Unsupported setup systemctl action: $1" >&2
            return 2
            ;;
    esac
    if ! load_state=$(setup_systemd_unit_load_state "$unit"); then
        return 1
    fi
    if [[ "$load_state" == masked ]]; then
        printf 'Skipping %s for administrator-masked unit: %s\n' "$1" "$unit"
        return 0
    fi
    sudo systemctl "$@" "$unit"
}
