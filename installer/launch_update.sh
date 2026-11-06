#!/usr/bin/env bash
set -euo pipefail

INSTALL_DIR="${KNXOH_INSTALL_DIR:-/opt/knx_to_openhab}"
APP_DIR="$INSTALL_DIR/current"
if [[ ! -x "$APP_DIR/venv/bin/python" || ! -f "$APP_DIR/installer/run_update_request.py" ]] || \
    ! "$APP_DIR/venv/bin/python" -c 'import sys' >/dev/null 2>&1; then
    APP_DIR="$INSTALL_DIR"
fi

if [[ ! -x "$APP_DIR/venv/bin/python" || ! -f "$APP_DIR/installer/run_update_request.py" ]]; then
    echo "No runnable KNX to OpenHAB updater found under $INSTALL_DIR" >&2
    exit 1
fi

exec "$APP_DIR/venv/bin/python" "$APP_DIR/installer/run_update_request.py"
