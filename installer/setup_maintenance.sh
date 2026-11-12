#!/usr/bin/env bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/maintenance_lock.sh"

SETUP_UPDATER_LOCK_HOLDER_PID=""
SETUP_UPDATER_LOCK_COMMAND_PID=""

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
        if acquire_setup_maintenance_exclusive_lock; then
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

acquire_setup_updater_locks() {
    local service_user="${1:-}"
    local timeout_seconds="${KNXOH_SETUP_UPDATER_TIMEOUT_SECONDS:-900}"
    local start_seconds=$SECONDS
    local ready_fd ready_message read_status lock_status command_pid
    local -a requested_lock_files=() lock_files=()
    local lock_file
    local -A seen_lock_files=()

    if (($# > 0)); then
        shift
        requested_lock_files=("$@")
    fi
    if [[ -z "$service_user" || ${#requested_lock_files[@]} -eq 0 ]]; then
        echo "ERROR: Setup updater locking requires a service user and lock paths." >&2
        return 2
    fi
    for lock_file in "${requested_lock_files[@]}"; do
        if [[ ! -v "seen_lock_files[$lock_file]" ]]; then
            seen_lock_files["$lock_file"]=1
            lock_files+=("$lock_file")
        fi
    done
    if [[ ! "$timeout_seconds" =~ ^[0-9]+$ ]]; then
        echo "ERROR: The setup updater-lock timeout must be a non-negative integer." >&2
        return 2
    fi

    while :; do
        coproc UPDATER_LOCK_HOLDER_PROCESS {
            exec sudo -u "$service_user" bash "$SCRIPT_DIR/hold_updater_locks.sh" "${lock_files[@]}"
        }
        SETUP_UPDATER_LOCK_HOLDER_PID="$UPDATER_LOCK_HOLDER_PROCESS_PID"
        ready_fd="${UPDATER_LOCK_HOLDER_PROCESS[0]}"
        if IFS= read -r -t 2 ready_message <&"$ready_fd"; then
            read_status=0
        else
            read_status=$?
        fi
        if (( read_status == 0 )) && [[ "$ready_message" =~ ^LOCKED\ ([0-9]+)$ ]]; then
            command_pid="${BASH_REMATCH[1]}"
            SETUP_UPDATER_LOCK_COMMAND_PID="$command_pid"
            exec {ready_fd}<&-
            return 0
        fi
        exec {ready_fd}<&-
        if (( read_status > 128 )); then
            kill -TERM "$SETUP_UPDATER_LOCK_HOLDER_PID" >/dev/null 2>&1 || true
            wait "$SETUP_UPDATER_LOCK_HOLDER_PID" 2>/dev/null || true
            SETUP_UPDATER_LOCK_HOLDER_PID=""
            echo "ERROR: Timed out waiting for updater-lock holder confirmation." >&2
            return 1
        fi
        if wait "$SETUP_UPDATER_LOCK_HOLDER_PID"; then
            lock_status=0
        else
            lock_status=$?
        fi
        SETUP_UPDATER_LOCK_HOLDER_PID=""
        if (( lock_status != 75 )); then
            echo "ERROR: Could not acquire setup updater lock (flock status $lock_status)." >&2
            return "$lock_status"
        fi
        if (( SECONDS - start_seconds >= timeout_seconds )); then
            echo "ERROR: Timed out waiting for updater locks." >&2
            return 1
        fi
        sleep 1
    done
}

release_setup_updater_locks() {
    local command_pid="${SETUP_UPDATER_LOCK_COMMAND_PID:-}"
    local holder_pid="${SETUP_UPDATER_LOCK_HOLDER_PID:-}"

    if [[ "$command_pid" =~ ^[0-9]+$ ]]; then
        sudo kill -TERM "$command_pid" >/dev/null 2>&1 || true
    fi
    if [[ "$holder_pid" =~ ^[0-9]+$ ]]; then
        kill -TERM "$holder_pid" >/dev/null 2>&1 || true
        wait "$holder_pid" 2>/dev/null || true
    fi
    SETUP_UPDATER_LOCK_COMMAND_PID=""
    SETUP_UPDATER_LOCK_HOLDER_PID=""
}
