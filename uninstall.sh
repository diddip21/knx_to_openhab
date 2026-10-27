#!/usr/bin/env bash
# Safe uninstaller for KNX to OpenHAB Generator.
# Usage: curl -fsSL https://raw.githubusercontent.com/diddip21/knx_to_openhab/main/uninstall.sh | bash

set -euo pipefail

SCRIPT_SOURCE="${BASH_SOURCE[0]-}"
if [[ -n "$SCRIPT_SOURCE" && "$SCRIPT_SOURCE" != "bash" ]]; then
    SCRIPT_DIR="$(cd "$(dirname "$SCRIPT_SOURCE")" && pwd)"
    HELPER="$SCRIPT_DIR/installer/uninstall.py"
    if [[ -f "$HELPER" ]]; then
        exec python3 "$HELPER" "$@"
    fi
fi

# When this file is piped to Bash, fetch the standalone helper as well. Read
# confirmations from the terminal, not the pipe that supplied this script.
TEMP_HELPER="$(mktemp)"
trap 'rm -f "$TEMP_HELPER"' EXIT
curl -fsSL \
    "https://raw.githubusercontent.com/diddip21/knx_to_openhab/main/installer/uninstall.py" \
    -o "$TEMP_HELPER"

if [[ -e /dev/tty ]] && ( : </dev/tty ) 2>/dev/null; then
    python3 "$TEMP_HELPER" "$@" </dev/tty
else
    python3 "$TEMP_HELPER" "$@"
fi
