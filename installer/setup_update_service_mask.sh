#!/usr/bin/env bash

KNXOH_UPDATE_SERVICE_RUNTIME_MASKED=0

mask_update_service_for_setup() {
    local unit="knxohui-update.service"
    local load_state

    if ! load_state=$(sudo systemctl show --property=LoadState --value "$unit"); then
        echo "ERROR: Could not inspect the updater unit before setup." >&2
        return 1
    fi

    case "$load_state" in
        not-found|masked)
            return 0
            ;;
        loaded) ;;
        *)
            echo "ERROR: Unknown updater unit load state: $load_state" >&2
            return 1
            ;;
    esac

    if ! sudo systemctl mask --runtime "$unit"; then
        echo "ERROR: Could not runtime-mask the updater unit for setup." >&2
        return 1
    fi

    KNXOH_UPDATE_SERVICE_RUNTIME_MASKED=1
}

unmask_update_service_after_setup() {
    local unit="knxohui-update.service"

    [[ "${KNXOH_UPDATE_SERVICE_RUNTIME_MASKED:-0}" == 1 ]] || return 0

    if ! sudo systemctl unmask --runtime "$unit"; then
        echo "ERROR: Could not remove the setup-owned updater runtime mask." >&2
        return 1
    fi

    KNXOH_UPDATE_SERVICE_RUNTIME_MASKED=0
}
