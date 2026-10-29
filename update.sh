#!/usr/bin/env bash
# Compatibility client only. Run as the Web UI service identity, never as root.
set -euo pipefail
if [[ "$EUID" -eq 0 ]]; then
    echo "Run the update client as the Web UI service identity, not root." >&2
    exit 1
fi
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$SCRIPT_DIR"
# An administrator install may retain the wrapper at the managed base; the client
# belongs to the active application, NOT the privileged libexec bundle.
if [[ -d "$SCRIPT_DIR/current" ]]; then
    APP_DIR="$SCRIPT_DIR/current"
fi
if [[ ! -r "$APP_DIR/installer/update_submit.py" ]]; then
    echo "Verified updater client missing. Use the verified administrator bootstrap for one-time setup/repair." >&2
    exit 1
fi
PYTHON="$APP_DIR/venv/bin/python"
if [[ ! -x "$PYTHON" ]]; then
    PYTHON=/usr/bin/python3
fi
cd "$APP_DIR"
exec "$PYTHON" -m installer.update_submit "$@"
