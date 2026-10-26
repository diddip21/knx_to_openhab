#!/usr/bin/env bash
set -euo pipefail

INSTALL_DIR="${KNXOH_INSTALL_DIR:-/opt/knx_to_openhab}"
APP_DIR="$INSTALL_DIR/current"
if [[ ! -f "$APP_DIR/installer/backup_cleanup.sh" ]]; then
    APP_DIR="$INSTALL_DIR"
fi

if [[ ! -f "$APP_DIR/installer/backup_cleanup.sh" ]]; then
    echo "No KNX to openHAB installer found under $INSTALL_DIR" >&2
    exit 1
fi

exec /bin/bash "$APP_DIR/installer/backup_cleanup.sh"
