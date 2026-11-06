#!/usr/bin/env bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/maintenance_lock.sh"

acquire_setup_maintenance_lock() {
    local quiesce_function="${1:-}"
    local timeout_seconds="${KNXOH_SETUP_MAINTENANCE_TIMEOUT_SECONDS:-900}"
    local start_seconds=$SECONDS
    local lock_status

    if [[ -z "$quiesce_function" ]] || ! declare -F "$quiesce_function" >/dev/null; then
        echo "ERROR: Setup maintenance requires a service-quiescence function." >&2
        return 2
    fi
    if [[ ! "$timeout_seconds" =~ ^[0-9]+$ ]]; then
        echo "ERROR: The setup maintenance timeout must be a non-negative integer." >&2
        return 2
    fi

    while :; do
        if ! "$quiesce_function"; then
            echo "ERROR: Could not quiesce services before setup maintenance." >&2
            return 1
        fi
        if acquire_maintenance_exclusive_lock; then
            if "$quiesce_function"; then
                return 0
            fi
            release_maintenance_lock || true
            echo "ERROR: Services did not remain quiescent after acquiring the setup lock." >&2
            return 1
        else
            lock_status=$?
        fi
        if (( lock_status != 1 )); then
            echo "ERROR: Could not acquire the setup maintenance lock (flock status $lock_status)." >&2
            return "$lock_status"
        fi
        if (( SECONDS - start_seconds >= timeout_seconds )); then
            echo "ERROR: Timed out waiting for the setup maintenance lock." >&2
            return 1
        fi
        sleep 1
    done
}
