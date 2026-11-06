#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ ! -f "$SCRIPT_DIR/maintenance_lock.sh" ]]; then
    echo "ERROR: The maintenance lock helper is missing." >&2
    exit 1
fi
source "$SCRIPT_DIR/maintenance_lock.sh"
if ! acquire_maintenance_shared_lock; then
    echo "ERROR: Setup or uninstall is in progress; retry backup cleanup later." >&2
    exit 1
fi

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
