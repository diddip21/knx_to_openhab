#!/usr/bin/env bash
set -euo pipefail

UNIT="${1:-}"
QUIESCE_TIMEOUT_SECONDS="${KNXOH_SETUP_UNIT_QUIESCE_TIMEOUT_SECONDS:-900}"

fail() {
    printf 'ERROR: %s\n' "$1" >&2
    exit 1
}

if [[ -z "$UNIT" || "$UNIT" == -* || "$UNIT" != *.service && "$UNIT" != *.timer ]]; then
    fail "A service or timer unit name is required."
fi
if [[ ! "$QUIESCE_TIMEOUT_SECONDS" =~ ^[0-9]+$ ]]; then
    fail "The unit quiesce timeout must be a non-negative integer."
fi
if ! command -v sudo >/dev/null 2>&1; then
    fail "The sudo command is required to inspect systemd units."
fi

if ! LOAD_STATE=$(sudo systemctl show --property=LoadState --value "$UNIT"); then
    fail "Could not inspect the load state for $UNIT."
fi
case "$LOAD_STATE" in
    loaded|masked|not-found) ;;
    *) fail "Unknown load state for $UNIT: $LOAD_STATE" ;;
esac

START_SECONDS=$SECONDS
while :; do
    if (( SECONDS - START_SECONDS >= QUIESCE_TIMEOUT_SECONDS )); then
        fail "Timed out waiting for $UNIT to quiesce."
    fi

    if ! ACTIVE_STATE=$(sudo systemctl show --property=ActiveState --value "$UNIT"); then
        fail "Could not inspect the active state for $UNIT."
    fi
    case "$ACTIVE_STATE" in
        active|activating|deactivating|reloading)
            if ! sudo systemctl stop "$UNIT"; then
                fail "Could not stop active unit $UNIT."
            fi
            sleep 1
            continue
            ;;
        inactive|failed|dead|not-found) ;;
        *) fail "Unknown active state for $UNIT: $ACTIVE_STATE" ;;
    esac

    if ! PENDING_JOBS=$(sudo systemctl list-jobs --no-legend --no-pager "$UNIT"); then
        fail "Could not inspect pending jobs for $UNIT."
    fi
    HAS_PENDING_JOB=0
    while read -r JOB_ID JOB_UNIT JOB_TYPE _JOB_STATE; do
        [[ "$JOB_UNIT" == "$UNIT" ]] || continue
        HAS_PENDING_JOB=1
        if [[ "$JOB_TYPE" != stop ]]; then
            if ! sudo systemctl cancel "$JOB_ID"; then
                fail "Could not cancel pending job $JOB_ID for $UNIT."
            fi
        fi
    done <<<"$PENDING_JOBS"
    if (( HAS_PENDING_JOB )); then
        sleep 1
        continue
    fi

    if ! ACTIVE_STATE=$(sudo systemctl show --property=ActiveState --value "$UNIT"); then
        fail "Could not recheck the active state for $UNIT."
    fi
    case "$ACTIVE_STATE" in
        inactive|failed|dead|not-found) ;;
        active|activating|deactivating|reloading)
            sleep 1
            continue
            ;;
        *) fail "Unknown active state for $UNIT: $ACTIVE_STATE" ;;
    esac
    if ! PENDING_JOBS=$(sudo systemctl list-jobs --no-legend --no-pager "$UNIT"); then
        fail "Could not recheck pending jobs for $UNIT."
    fi
    HAS_PENDING_JOB=0
    while read -r _JOB_ID JOB_UNIT _JOB_TYPE _JOB_STATE; do
        [[ "$JOB_UNIT" == "$UNIT" ]] && HAS_PENDING_JOB=1
    done <<<"$PENDING_JOBS"
    if (( HAS_PENDING_JOB )); then
        continue
    fi

    printf '%s is inactive with no pending jobs.\n' "$UNIT"
    exit 0
done
