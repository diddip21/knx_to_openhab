#!/usr/bin/env bash

KNXOH_MAINTENANCE_LOCK_FILE="${KNXOH_MAINTENANCE_LOCK_FILE:-/run/lock/knx_to_openhab/maintenance.lock}"
KNXOH_MAINTENANCE_LOCK_FD=""

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

    lock_dir="$(dirname -- "$KNXOH_MAINTENANCE_LOCK_FILE")"
    if [[ -L "$lock_dir" || ( -e "$lock_dir" && ! -d "$lock_dir" ) ]]; then
        echo "ERROR: The maintenance lock directory is unsafe: $lock_dir" >&2
        return 2
    fi
    if ! install -d -o root -g "$group_name" -m 0750 -- "$lock_dir"; then
        echo "ERROR: Could not create the maintenance lock directory: $lock_dir" >&2
        return 2
    fi

    if [[ -L "$KNXOH_MAINTENANCE_LOCK_FILE" || \
        ( -e "$KNXOH_MAINTENANCE_LOCK_FILE" && ! -f "$KNXOH_MAINTENANCE_LOCK_FILE" ) ]]; then
        echo "ERROR: The maintenance lock path is not a regular file." >&2
        return 2
    fi
    if [[ ! -e "$KNXOH_MAINTENANCE_LOCK_FILE" ]]; then
        if ! (set -o noclobber; : > "$KNXOH_MAINTENANCE_LOCK_FILE"); then
            if [[ -L "$KNXOH_MAINTENANCE_LOCK_FILE" || ! -f "$KNXOH_MAINTENANCE_LOCK_FILE" ]]; then
                echo "ERROR: Could not safely create the maintenance lock file." >&2
                return 2
            fi
        fi
    fi
    if ! chown "root:$group_name" -- "$KNXOH_MAINTENANCE_LOCK_FILE" || \
        ! chmod 0660 -- "$KNXOH_MAINTENANCE_LOCK_FILE"; then
        echo "ERROR: Could not secure the maintenance lock file." >&2
        return 2
    fi
}

_acquire_maintenance_lock() {
    local mode="$1"
    local fd
    local status

    if [[ -n "$KNXOH_MAINTENANCE_LOCK_FD" ]]; then
        echo "ERROR: This process already holds a maintenance lock." >&2
        return 2
    fi
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

release_maintenance_lock() {
    local fd="${KNXOH_MAINTENANCE_LOCK_FD:-}"
    local status=0

    [[ -n "$fd" ]] || return 0
    flock --unlock "$fd" || status=$?
    exec {fd}>&-
    KNXOH_MAINTENANCE_LOCK_FD=""
    return "$status"
}
