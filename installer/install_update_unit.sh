#!/usr/bin/env bash
set -euo pipefail

SOURCE_UNIT="${1:-}"
DESTINATION="${2:-}"
UNIT="knxohui-update.service"

if [[ -z "$SOURCE_UNIT" || -z "$DESTINATION" || ! -f "$SOURCE_UNIT" ]]; then
    echo "ERROR: An updater unit source and destination are required." >&2
    exit 2
fi
if ! LOAD_STATE=$(sudo systemctl show --property=LoadState --value "$UNIT"); then
    echo "ERROR: Could not inspect the updater unit before installation." >&2
    exit 1
fi
case "$LOAD_STATE" in
    masked)
        printf 'Preserving the administrator-masked updater unit.\n'
        exit 0
        ;;
    loaded|not-found) ;;
    *)
        echo "ERROR: Unknown updater unit load state: $LOAD_STATE" >&2
        exit 1
        ;;
esac

sudo install -o root -g root -m 0644 "$SOURCE_UNIT" "$DESTINATION"
