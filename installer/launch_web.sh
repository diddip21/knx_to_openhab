#!/usr/bin/env bash
set -euo pipefail

INSTALL_DIR="${KNXOH_INSTALL_DIR:-/opt/knx_to_openhab}"
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
