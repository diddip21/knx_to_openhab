#!/usr/bin/env bash

if [[ ! -v _KNXOH_MAINTENANCE_LOCK_ENV_OVERRIDE ]]; then
    _KNXOH_MAINTENANCE_LOCK_ENV_OVERRIDE="${KNXOH_MAINTENANCE_LOCK_FILE:-}"
fi
KNXOH_MAINTENANCE_LOCK_FILE="${KNXOH_MAINTENANCE_LOCK_FILE:-/run/lock/knx_to_openhab/maintenance.lock}"
KNXOH_MAINTENANCE_LOCK_FD=""

_maintenance_paths_overlap() {
    local left="$1" right="$2"
    [[ "$left" == "$right" || "$left" == "$right/"* || "$right" == "$left/"* ]]
}

resolve_maintenance_lock_path() {
    local paths_file="${1:-${KNXOH_PATHS_FILE:-/etc/knx_to_openhab/paths.env}}"
    local policy="${2:-strict}"
    local resolved_path

    case "$policy" in
        strict|allow-initial) ;;
        *)
            echo "ERROR: Unknown maintenance-lock resolution policy: $policy" >&2
            return 2
            ;;
    esac

    if ! resolved_path="$(python3 - "$paths_file" "$_KNXOH_MAINTENANCE_LOCK_ENV_OVERRIDE" \
        "$policy" <<'PY'
import shlex
import sys
from pathlib import Path

paths_file, override, policy = sys.argv[1:]
default_path = "/run/lock/knx_to_openhab/maintenance.lock"
lock_key = "KNXOH_MAINTENANCE_LOCK_FILE"
saved_path = None
registry = Path(paths_file)

def lock_key_variant(value):
    name = value.strip()
    if name == lock_key:
        return "exact"
    if name.startswith(lock_key):
        suffix = name[len(lock_key):]
        if suffix and not (suffix[0].isalnum() or suffix[0] == "_"):
            return "malformed"
    return None

if registry.is_symlink():
    raise SystemExit("The maintenance paths registry must not be a symlink")
if registry.exists():
    if not registry.is_file():
        raise SystemExit("The maintenance paths registry is not a regular file")
    for line in registry.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" not in stripped:
            if lock_key_variant(stripped) is not None:
                raise SystemExit("The persisted maintenance lock path is malformed")
            continue
        name, raw_value = stripped.split("=", 1)
        key_variant = lock_key_variant(name)
        if key_variant is None:
            continue
        if key_variant != "exact" or name != lock_key:
            raise SystemExit("The persisted maintenance lock path is malformed")
        if saved_path is not None:
            raise SystemExit("The paths registry contains a duplicate maintenance lock entry")
        try:
            values = shlex.split(raw_value, posix=True)
        except ValueError as error:
            raise SystemExit(f"The persisted maintenance lock path is malformed: {error}") from error
        if len(values) != 1 or not values[0]:
            raise SystemExit("The persisted maintenance lock path is malformed")
        saved_path = values[0]

def validate_path(value):
    if (
        not value
        or not value.startswith("/")
        or value == "/"
        or value.endswith("/")
        or "\n" in value
        or "\r" in value
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
        or any(part in {".", ".."} for part in value.split("/"))
    ):
        raise SystemExit("The maintenance lock path must be a safe absolute file path")

if override:
    validate_path(override)
if saved_path is not None:
    validate_path(saved_path)
    if override and override != saved_path:
        raise SystemExit("The maintenance lock override conflicts with the persisted path")
    selected_path = saved_path
elif override:
    if override != default_path and policy != "allow-initial":
        raise SystemExit("A custom runtime maintenance lock path is not persisted")
    selected_path = override
else:
    selected_path = default_path

validate_path(selected_path)
print(selected_path)
PY
    )"; then
        return 2
    fi
    KNXOH_MAINTENANCE_LOCK_FILE="$resolved_path"
    export KNXOH_MAINTENANCE_LOCK_FILE
}

_validate_maintenance_lock_ancestors() {
    local lock_file="$KNXOH_MAINTENANCE_LOCK_FILE"
    local current component lock_dir canonical_dir directory_state owner mode_text mode_value
    local -a components=()

    if [[ "$lock_file" != /* || "$lock_file" == */ || "$lock_file" == *$'\n'* || \
        "$lock_file" == *$'\r'* ]]; then
        echo "ERROR: The maintenance lock needs a safe absolute file path." >&2
        return 2
    fi
    case "/$lock_file/" in
        */./*|*/../*)
            echo "ERROR: The maintenance lock path has an unsafe component." >&2
            return 2
            ;;
    esac

    IFS='/' read -r -a components <<< "${lock_file#/}"
    current=""
    for component in "${components[@]}"; do
        [[ -n "$component" ]] || continue
        current+="/$component"
        if [[ -L "$current" ]]; then
            echo "ERROR: The maintenance lock needs a dedicated path without symlink components." >&2
            return 2
        fi
    done

    if [[ -e "$lock_file" ]]; then
        if [[ ! -f "$lock_file" ]]; then
            echo "ERROR: The maintenance lock path is not a regular file." >&2
            return 2
        fi
        if [[ "$(stat -c '%h' -- "$lock_file")" != 1 ]]; then
            echo "ERROR: The maintenance lock file must not have hard links." >&2
            return 2
        fi
    fi

    lock_dir="$(dirname -- "$lock_file")"
    canonical_dir="$(realpath -m -- "$lock_dir")" || {
        echo "ERROR: Could not normalize the maintenance lock directory." >&2
        return 2
    }
    IFS='/' read -r -a components <<< "${canonical_dir#/}"
    current=""
    for component in "${components[@]}"; do
        [[ -n "$component" ]] || continue
        current+="/$component"
        [[ -e "$current" ]] || break
        if [[ -L "$current" || ! -d "$current" ]]; then
            echo "ERROR: The maintenance lock ancestor is not a real directory: $current." >&2
            return 2
        fi
        directory_state="$(stat -c '%u:%a' -- "$current")" || {
            echo "ERROR: Could not inspect the maintenance lock ancestor: $current." >&2
            return 2
        }
        IFS=: read -r owner mode_text <<< "$directory_state"
        mode_value=$((8#$mode_text))
        if [[ "$owner" != 0 ]] || \
            { (( mode_value & 0022 )) && ! (( mode_value & 01000 )); }; then
            echo "ERROR: The maintenance lock path has an untrusted writable ancestor: $current." >&2
            return 2
        fi
    done
}

validate_maintenance_lock_location() {
    local group_name="${1:-knxohui}"
    if (($#)); then
        shift
    fi
    local lock_file="$KNXOH_MAINTENANCE_LOCK_FILE"
    local lock_dir canonical_dir managed_path current component group_entry group_gid directory_state
    local -a components=()

    _validate_maintenance_lock_ancestors || return $?

    lock_dir="$(dirname -- "$lock_file")"
    canonical_dir="$(realpath -m -- "$lock_dir")" || {
        echo "ERROR: Could not normalize the maintenance lock directory." >&2
        return 2
    }
    case "$canonical_dir" in
        /|/tmp|/var/lock|/run/lock|/var/run|/run|/var|/var/lib|/var/backups| \
        /var/cache|/var/log|/var/tmp|/var/spool|/var/mail|/var/www|/var/opt| \
        /etc|/usr|/usr/local|/usr/bin|/usr/sbin|/usr/lib|/usr/lib64|/usr/share| \
        /usr/include|/usr/src|/usr/games|/home|/root|/opt|/srv|/mnt|/media|/boot| \
        /dev|/proc|/sys|/run/user|/run/systemd|/run/udev|/run/credentials)
            echo "ERROR: The maintenance lock needs a dedicated parent directory, not $canonical_dir." >&2
            return 2
            ;;
    esac

    if [[ -e "$canonical_dir" ]]; then
        if [[ ! -d "$canonical_dir" || -L "$canonical_dir" ]]; then
            echo "ERROR: The maintenance lock parent must be a dedicated directory: $canonical_dir." >&2
            return 2
        fi
        directory_state="$(stat -c '%u:%g:%a' -- "$canonical_dir")" || {
            echo "ERROR: Could not inspect the maintenance lock parent: $canonical_dir." >&2
            return 2
        }
        group_entry="$(getent group "$group_name" 2>/dev/null || true)"
        if [[ -n "$group_entry" ]]; then
            IFS=: read -r _ _ group_gid _ <<<"$group_entry"
        else
            group_gid=0
        fi
        if [[ "$directory_state" != "0:$group_gid:750" ]]; then
            echo "ERROR: The existing maintenance lock parent is not a dedicated root:$group_name 0750 directory: $canonical_dir." >&2
            return 2
        fi
    fi

    for managed_path in "$@"; do
        [[ -n "$managed_path" ]] || continue
        managed_path="$(realpath -m -- "$managed_path")" || {
            echo "ERROR: Could not normalize a managed path for maintenance lock validation." >&2
            return 2
        }
        if _maintenance_paths_overlap "$canonical_dir" "$managed_path"; then
            echo "ERROR: The maintenance lock needs a dedicated parent outside managed paths: $canonical_dir." >&2
            return 2
        fi
    done
}

ensure_maintenance_lock() {
    local group_name="${1:-}"
    local lock_dir

    if (( EUID != 0 )); then
        echo "ERROR: Creating the maintenance lock requires root privileges." >&2
        return 2
    fi
    if [[ -z "$group_name" || "$KNXOH_MAINTENANCE_LOCK_FILE" != /* ]]; then
        echo "ERROR: The maintenance lock needs a group and an absolute path." >&2
        return 2
    fi
    validate_maintenance_lock_location "$group_name" || return $?

    lock_dir="$(dirname -- "$KNXOH_MAINTENANCE_LOCK_FILE")"
    if [[ -L "$lock_dir" || ( -e "$lock_dir" && ! -d "$lock_dir" ) ]]; then
        echo "ERROR: The maintenance lock directory is unsafe: $lock_dir" >&2
        return 2
    fi
    if [[ ! -e "$lock_dir" ]]; then
        if ! install -d -o root -g "$group_name" -m 0750 -- "$lock_dir"; then
            echo "ERROR: Could not create the maintenance lock directory: $lock_dir" >&2
            return 2
        fi
    fi

    if ! python3 - "$KNXOH_MAINTENANCE_LOCK_FILE" "$group_name" <<'PY'
import grp
import os
import stat
import sys

lock_file, group_name = sys.argv[1:]
try:
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(lock_file, flags, 0o660)
    try:
        lock_stat = os.fstat(descriptor)
        if not stat.S_ISREG(lock_stat.st_mode):
            raise OSError("the lock path is not a regular file")
        if lock_stat.st_nlink != 1:
            raise OSError("the lock file must not have hard links")
        group_id = grp.getgrnam(group_name).gr_gid
        os.fchown(descriptor, 0, group_id)
        os.fchmod(descriptor, 0o660)
    finally:
        os.close(descriptor)
except (OSError, KeyError) as error:
    print(f"ERROR: Could not securely prepare the maintenance lock file: {error}", file=sys.stderr)
    raise SystemExit(2)
PY
    then
        echo "ERROR: Could not secure the maintenance lock file." >&2
        return 2
    fi
}

_acquire_maintenance_lock() {
    local mode="$1"
    local resolution_policy="${2:-strict}"
    local fd
    local status

    if [[ -n "$KNXOH_MAINTENANCE_LOCK_FD" ]]; then
        echo "ERROR: This process already holds a maintenance lock." >&2
        return 2
    fi
    resolve_maintenance_lock_path "${KNXOH_PATHS_FILE:-/etc/knx_to_openhab/paths.env}" \
        "$resolution_policy" || return $?
    _validate_maintenance_lock_ancestors || return $?
    if [[ -L "$KNXOH_MAINTENANCE_LOCK_FILE" || ! -f "$KNXOH_MAINTENANCE_LOCK_FILE" ]]; then
        echo "ERROR: The maintenance lock file is missing or unsafe." >&2
        return 2
    fi
    if ! exec {fd}>>"$KNXOH_MAINTENANCE_LOCK_FILE"; then
        echo "ERROR: Could not open the maintenance lock file." >&2
        return 2
    fi
    if flock "$mode" --nonblock "$fd"; then
        KNXOH_MAINTENANCE_LOCK_FD="$fd"
        return 0
    else
        status=$?
        exec {fd}>&-
        return "$status"
    fi
}

acquire_maintenance_shared_lock() {
    _acquire_maintenance_lock --shared
}

acquire_maintenance_exclusive_lock() {
    _acquire_maintenance_lock --exclusive
}

acquire_setup_maintenance_exclusive_lock() {
    _acquire_maintenance_lock --exclusive allow-initial
}

release_maintenance_lock() {
    local fd="${KNXOH_MAINTENANCE_LOCK_FD:-}"
    local status=0

    [[ -n "$fd" ]] || return 0
    flock --unlock "$fd" || status=$?
    exec {fd}>&-
    KNXOH_MAINTENANCE_LOCK_FD=""
    return "$status"
}
