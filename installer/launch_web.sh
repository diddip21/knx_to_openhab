#!/usr/bin/env bash
set -euo pipefail

INSTALL_DIR="${KNXOH_INSTALL_DIR:-/opt/knx_to_openhab}"
GUARD=/usr/local/libexec/knx_to_openhab/update_start_guard.py
if [[ -f "$GUARD" ]]; then
    /usr/bin/python3 -I "$GUARD" \
        --releases "$INSTALL_DIR/releases" --current "$INSTALL_DIR/current" \
        --config-dir "${KNXOH_CONFIG_DIR:-/etc/knx_to_openhab}" --role ui
elif [[ "$0" == /usr/local/libexec/knx_to_openhab/* || -d "$INSTALL_DIR/releases" ]]; then
    echo "Missing protected updater startup guard; run verified administrator bootstrap." >&2
    exit 1
fi
APP_DIR="$INSTALL_DIR/current"
if [[ ! -x "$APP_DIR/venv/bin/gunicorn" ]]; then
    APP_DIR="$INSTALL_DIR"
fi

if [[ ! -x "$APP_DIR/venv/bin/gunicorn" ]]; then
    echo "No runnable KNX to openHAB release found under $INSTALL_DIR" >&2
    exit 1
fi

cd "$APP_DIR"
export PATH="$APP_DIR/venv/bin:/usr/bin:/bin"
export PYTHONPATH="$APP_DIR${PYTHONPATH:+:$PYTHONPATH}"
exec "$APP_DIR/venv/bin/gunicorn" \
    -c "$APP_DIR/web_ui/backend/gunicorn_conf.py" \
    web_ui.backend.app:app
