#!/usr/bin/env bash
set -euo pipefail

INSTALL_DIR="${KNXOH_INSTALL_DIR:-/opt/knx_to_openhab}"
GUARD=/usr/local/libexec/knx_to_openhab/update_start_guard.py
if [[ -f "$GUARD" ]]; then
    /usr/bin/python3 -I "$GUARD" \
        --releases "$INSTALL_DIR/releases" --current "$INSTALL_DIR/current" \
        --config-dir "${KNXOH_CONFIG_DIR:-/etc/knx_to_openhab}" --role cleanup
elif [[ "$0" == /usr/local/libexec/knx_to_openhab/* || -d "$INSTALL_DIR/releases" ]]; then
    echo "Missing protected updater startup guard; run verified administrator bootstrap." >&2
    exit 1
fi
APP_DIR="$INSTALL_DIR/current"
if [[ ! -f "$APP_DIR/installer/backup_cleanup.sh" ]]; then
    APP_DIR="$INSTALL_DIR"
fi

if [[ ! -f "$APP_DIR/installer/backup_cleanup.sh" ]]; then
    echo "No KNX to openHAB installer found under $INSTALL_DIR" >&2
    exit 1
fi

exec /bin/bash "$APP_DIR/installer/backup_cleanup.sh"
