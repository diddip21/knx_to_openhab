#!/usr/bin/env bash
set -euo pipefail

UNIT="knxohui-update.service"
QUIESCE_TIMEOUT_SECONDS="${KNXOH_SETUP_UPDATER_QUIESCE_TIMEOUT_SECONDS:-900}"

fail() {
    printf 'ERROR: %s\n' "$1" >&2
    exit 1
}

if [[ ! "$QUIESCE_TIMEOUT_SECONDS" =~ ^[0-9]+$ ]]; then
    fail "The updater quiesce timeout must be a non-negative integer."
fi

if ! LOAD_STATE=$(sudo systemctl show --property=LoadState --value "$UNIT"); then
    fail "Could not inspect the updater unit load state."
fi
case "$LOAD_STATE" in
    loaded|masked|not-found) ;;
    *)
        fail "The updater unit load state is unknown."
        ;;
esac

START_SECONDS=$SECONDS
while :; do
    if (( SECONDS - START_SECONDS >= QUIESCE_TIMEOUT_SECONDS )); then
        fail "Timed out waiting for the updater to quiesce."
    fi

    if ! ACTIVE_STATE=$(sudo systemctl show --property=ActiveState --value "$UNIT"); then
        fail "Could not inspect updater state."
    fi
    case "$ACTIVE_STATE" in
        active|activating|deactivating|reloading)
            sleep 1
            continue
            ;;
        inactive|failed|dead) ;;
        not-found) ;;
        *) fail "Unknown updater state: $ACTIVE_STATE" ;;
    esac

    if ! PENDING_JOBS=$(sudo systemctl list-jobs --no-legend --no-pager "$UNIT"); then
        fail "Could not inspect pending updater jobs."
    fi
    HAS_PENDING_JOB=0
    while read -r JOB_ID JOB_UNIT JOB_TYPE JOB_STATE; do
        [[ "$JOB_UNIT" == "$UNIT" ]] || continue
        HAS_PENDING_JOB=1
        if [[ "$JOB_TYPE" != stop ]]; then
            if ! sudo systemctl cancel "$JOB_ID"; then
                fail "Could not cancel pending updater job $JOB_ID."
            fi
        fi
    done <<<"$PENDING_JOBS"
    if (( HAS_PENDING_JOB )); then
        sleep 1
        continue
    fi

    # Confirm both state and job queue again after cancellation to close the
    # transition window between systemd's state and job queries.
    if ! ACTIVE_STATE=$(sudo systemctl show --property=ActiveState --value "$UNIT"); then
        fail "Could not recheck updater state."
    fi
    case "$ACTIVE_STATE" in
        inactive|failed|dead) ;;
        active|activating|deactivating|reloading)
            sleep 1
            continue
            ;;
        not-found) ;;
        *) fail "Unknown updater state: $ACTIVE_STATE" ;;
    esac
    if ! PENDING_JOBS=$(sudo systemctl list-jobs --no-legend --no-pager "$UNIT"); then
        fail "Could not recheck pending updater jobs."
    fi
    HAS_PENDING_JOB=0
    while read -r JOB_ID JOB_UNIT _JOB_TYPE _JOB_STATE; do
        [[ "$JOB_UNIT" == "$UNIT" ]] && HAS_PENDING_JOB=1
    done <<<"$PENDING_JOBS"
    if (( HAS_PENDING_JOB )); then
        continue
    fi

    printf 'Updater is inactive with no pending jobs; setup may proceed.\n'
    exit 0
done
