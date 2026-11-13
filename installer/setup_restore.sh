#!/usr/bin/env bash

# Sourced by setup.sh so the failure path can be exercised without host writes.
restore_previous_services() {
    local exit_status=$?
    trap - EXIT
    release_setup_updater_locks || echo "Could not release setup updater locks." >&2
    if ! release_maintenance_lock; then
        echo "Could not release the setup maintenance lock." >&2
    fi
    if (( exit_status != 0 && SETUP_COMPLETED == 0 && ${#PREVIOUSLY_ACTIVE_UNITS[@]} > 0 )); then
        echo "Setup failed; restoring services that were active before migration." >&2
        sudo systemctl daemon-reload || true
        for unit in "${PREVIOUSLY_ACTIVE_UNITS[@]}"; do
            if ! sudo systemctl start "$unit"; then
                echo "Could not restore $unit. Check it with: sudo systemctl status $unit" >&2
            fi
        done
    fi
    exit "$exit_status"
}
