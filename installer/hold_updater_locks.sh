#!/usr/bin/env bash
set -euo pipefail

if (($# == 0)); then
    echo "ERROR: At least one updater lock path is required." >&2
    exit 2
fi

if ! command -v flock >/dev/null 2>&1; then
    echo "ERROR: The 'flock' utility is required to hold updater locks." >&2
    exit 2
fi

declare -a LOCK_FDS=()
for lock_file in "$@"; do
    if [[ "$lock_file" != /* || -L "$lock_file" || \
        ( -e "$lock_file" && ! -f "$lock_file" ) ]]; then
        echo "ERROR: Updater lock path is unsafe: $lock_file" >&2
        exit 2
    fi
    if ! exec {lock_fd}>>"$lock_file"; then
        echo "ERROR: Could not open updater lock: $lock_file" >&2
        exit 2
    fi
    if flock --exclusive --nonblock --conflict-exit-code 75 "$lock_fd"; then
        LOCK_FDS+=("$lock_fd")
    else
        lock_status=$?
        exit "$lock_status"
    fi
done

printf 'LOCKED %s\n' "$$"
exec sleep infinity
