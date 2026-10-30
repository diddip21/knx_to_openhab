#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PATHS_FILE="/etc/knx_to_openhab/paths.env"
SERVICE_USER="knxohui"

read_saved_path() {
    python3 - "$PATHS_FILE" "$1" "$2" <<'PY'
import shlex
import sys

path_file, wanted, fallback = sys.argv[1:]
try:
    lines = open(path_file, encoding="utf-8").read().splitlines()
except FileNotFoundError:
    print(fallback)
    raise SystemExit(0)
for line in lines:
    if "=" not in line:
        continue
    name, value = line.strip().split("=", 1)
    if name == wanted:
        parsed = shlex.split(value, posix=True)
        if len(parsed) == 1:
            print(parsed[0])
            raise SystemExit(0)
print(fallback)
PY
}

BASE="${KNXOH_INSTALL_DIR:-$(read_saved_path KNXOH_INSTALL_DIR /opt/knx_to_openhab)}"
CONFIG_DIR="${KNXOH_CONFIG_DIR:-$(read_saved_path KNXOH_CONFIG_DIR /etc/knx_to_openhab)}"
DATA_DIR="${KNXOH_DATA_DIR:-$(read_saved_path KNXOH_DATA_DIR /var/lib/knx_to_openhab)}"
BACKUP_DIR="${KNXOH_BACKUP_DIR:-$(read_saved_path KNXOH_BACKUP_DIR /var/backups/knx_to_openhab)}"

NORMALIZED_PATHS=$(python3 - "$BASE" "$CONFIG_DIR" "$DATA_DIR" "$BACKUP_DIR" <<'PY'
import sys
from pathlib import Path

raw_paths = [Path(value).expanduser() for value in sys.argv[1:]]
for path in raw_paths:
    if not path.is_absolute():
        raise SystemExit(f"Installation paths must be absolute: {path}")
base, config, data, backups = (path.resolve() for path in raw_paths)
paths = {"application": base, "configuration": config, "runtime data": data, "backups": backups}
for label, path in paths.items():
    if not path.is_absolute() or path == Path(path.anchor):
        raise SystemExit(f"{label} path must be a non-root absolute path: {path}")
    if label != "application" and (path == base or base in path.parents):
        raise SystemExit(f"{label} must be outside the application directory: {path}")
    if str(path) in {"/etc", "/var", "/usr", "/opt", "/home", "/root", "/tmp"}:
        raise SystemExit(f"Refusing a system-wide path as {label}: {path}")

external = (config, data, backups)
for index, left in enumerate(external):
    for right in external[index + 1 :]:
        if left == right or left in right.parents or right in left.parents:
            raise SystemExit(f"Configuration, runtime and backup paths must not overlap: {left}, {right}")

print(base)
print(config)
print(data)
print(backups)
PY
) || exit 2
mapfile -t NORMALIZED_PATH_LIST <<<"$NORMALIZED_PATHS"
BASE="${NORMALIZED_PATH_LIST[0]}"
CONFIG_DIR="${NORMALIZED_PATH_LIST[1]}"
DATA_DIR="${NORMALIZED_PATH_LIST[2]}"
BACKUP_DIR="${NORMALIZED_PATH_LIST[3]}"

echo "Using application directory: $BASE"
echo "Using configuration directory: $CONFIG_DIR"
echo "Using runtime data directory: $DATA_DIR"
echo "Using backup directory: $BACKUP_DIR"

stop_unit_if_active() {
    local unit="$1"
    if sudo systemctl is-active --quiet "$unit"; then
        sudo systemctl stop "$unit"
    fi
}

AUTH_PREFLIGHT_CONFIG="$CONFIG_DIR/config.json"
if [[ ! -f "$AUTH_PREFLIGHT_CONFIG" && -f "$BASE/web_ui/backend/config.json" ]]; then
    AUTH_PREFLIGHT_CONFIG="$BASE/web_ui/backend/config.json"
elif [[ ! -f "$AUTH_PREFLIGHT_CONFIG" && -f "$REPO_ROOT/web_ui/backend/config.json" ]]; then
    AUTH_PREFLIGHT_CONFIG="$REPO_ROOT/web_ui/backend/config.json"
fi
AUTH_PREFLIGHT_STATUS=1
if [[ -x "$BASE/venv/bin/python" ]]; then
    if PYTHONPATH="$BASE" "$BASE/venv/bin/python" - "$AUTH_PREFLIGHT_CONFIG" "$CONFIG_DIR/secrets.env" <<'PY'
import base64
import binascii
import json
import sys
from pathlib import Path

from web_ui.backend.auth import is_password_hash, verify_password

config_path, secrets_path = map(Path, sys.argv[1:])
try:
    config = json.loads(config_path.read_text(encoding="utf-8")) if config_path.is_file() else {}
except (OSError, json.JSONDecodeError):
    raise SystemExit(2)
auth = config.get("auth", {}) if isinstance(config, dict) else {}
if not isinstance(auth, dict):
    raise SystemExit(2)
authentication_enabled = auth.get("enabled", True)
encoded_hash = None
legacy_encoded = None
if secrets_path.is_file():
    try:
        for line in secrets_path.read_text(encoding="utf-8").splitlines():
            name, separator, value = line.partition("=")
            if not separator:
                continue
            if name == "KNXOH_UI_PASSWORD_HASH_B64":
                encoded_hash = value.strip()
            elif name == "KNXOH_UI_PASSWORD_B64":
                legacy_encoded = value.strip()
    except OSError:
        raise SystemExit(2)
if encoded_hash:
    try:
        password_hash = base64.b64decode(encoded_hash, validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError):
        raise SystemExit(2)
    if not is_password_hash(password_hash):
        raise SystemExit(2)
    if not verify_password(password_hash, "logihome"):
        raise SystemExit(0)
    if authentication_enabled is False:
        raise SystemExit(0)
    raise SystemExit(1)
if legacy_encoded:
    try:
        legacy_password = base64.b64decode(legacy_encoded, validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError):
        raise SystemExit(2)
    if legacy_password != "logihome":
        raise SystemExit(0)
legacy_password = auth.get("password", auth.get("legacy_password"))
if legacy_password is not None and str(legacy_password) != "logihome":
    raise SystemExit(0)
if authentication_enabled is False:
    raise SystemExit(0)
raise SystemExit(1)
PY
    then
        AUTH_PREFLIGHT_STATUS=0
    else
        AUTH_PREFLIGHT_STATUS=$?
    fi
fi
if [[ "$AUTH_PREFLIGHT_STATUS" -eq 2 ]]; then
    echo "The existing Web UI credential configuration is invalid." >&2
    echo "No service, package or runtime data was changed." >&2
    exit 4
fi
if [[ "$AUTH_PREFLIGHT_STATUS" -ne 0 ]]; then
    if ! { exec 3<>/dev/tty; } 2>/dev/null; then
        echo "Credential migration needs an interactive terminal." >&2
        echo "Run setup from an interactive SSH session (for example, ssh -t)." >&2
        echo "No service, package or runtime data was changed." >&2
        exit 4
    fi
    exec 3>&-
fi
PREVIOUSLY_ACTIVE_UNITS=()
for unit in knxohui-backup-cleanup.timer knxohui-backup-cleanup.service knxohui.service; do
    if sudo systemctl is-active --quiet "$unit"; then
        PREVIOUSLY_ACTIVE_UNITS+=("$unit")
    fi
done
SETUP_COMPLETED=0

restore_previous_services() {
    local exit_status=$?
    trap - EXIT
    if (( exit_status != 0 && SETUP_COMPLETED == 0 && ${#PREVIOUSLY_ACTIVE_UNITS[@]} > 0 )); then
        echo "Setup failed; restoring services that were active before migration." >&2
        sudo systemctl daemon-reload || true
        for unit in "${PREVIOUSLY_ACTIVE_UNITS[@]}"; do
            if ! sudo systemctl start "$unit"; then
                echo "Could not restore $unit. Check it with: sudo systemctl status $unit" >&2
            fi
        done
    fi
    exit "$exit_status"
}
trap restore_previous_services EXIT
echo "Stopping the Web UI and backup cleanup during migration"
stop_unit_if_active knxohui-backup-cleanup.timer
stop_unit_if_active knxohui-backup-cleanup.service
stop_unit_if_active knxohui.service

if ! getent group "$SERVICE_USER" >/dev/null 2>&1; then
    sudo groupadd -r "$SERVICE_USER"
fi
if ! id -u "$SERVICE_USER" >/dev/null 2>&1; then
    sudo useradd -r -g "$SERVICE_USER" -s /usr/sbin/nologin "$SERVICE_USER"
fi

sudo mkdir -p "$BASE"
sudo chown "$SERVICE_USER":"$SERVICE_USER" "$BASE"

sudo python3 -m venv "$BASE/venv"
sudo "$BASE/venv/bin/pip" install --upgrade pip
sudo "$BASE/venv/bin/pip" install -r "$REPO_ROOT/requirements.txt"

echo "Installing application files while preserving runtime configuration"
sudo rsync -a --exclude .git --exclude /config.json \
    --exclude web_ui/backend/config.json "$REPO_ROOT/" "$BASE/"
if [[ ! -f "$BASE/config.json" ]]; then
    sudo install -o "$SERVICE_USER" -g "$SERVICE_USER" -m 0640 \
        "$REPO_ROOT/config.json" "$BASE/config.json"
fi
sudo install -o root -g root -m 0755 \
    "$REPO_ROOT/installer/service_update.sh" \
    /usr/local/sbin/knxohui-service-update
sudo install -d -o root -g root -m 0755 /usr/local/libexec/knx_to_openhab
sudo install -o root -g root -m 0755 \
    "$BASE/installer/provision_managed_outputs.py" \
    /usr/local/libexec/knx_to_openhab/provision_managed_outputs.py

echo "Migrating configuration, jobs, staging data and backups"
sudo "$BASE/venv/bin/python" "$BASE/installer/migrate_runtime_data.py" \
    --source-root "$BASE" \
    --template-root "$REPO_ROOT" \
    --config-dir "$CONFIG_DIR" \
    --data-dir "$DATA_DIR" \
    --backup-dir "$BACKUP_DIR" \
    --install-dir "$BASE" \
    --paths-file "$PATHS_FILE"

echo "Checking the Web UI network binding"
sudo "$BASE/venv/bin/python" "$BASE/installer/configure_bind.py" \
    "$CONFIG_DIR/config.json"

export KNXOH_INSTALL_DIR="$BASE"
export KNXOH_CONFIG_DIR="$CONFIG_DIR"
export KNXOH_DATA_DIR="$DATA_DIR"
export KNXOH_BACKUP_DIR="$BACKUP_DIR"
export KNXOH_PATHS_FILE="$PATHS_FILE"
CONF="$CONFIG_DIR/config.json"
PORT=$(python3 - "$CONF" <<'PY'
import json
import sys
with open(sys.argv[1], encoding="utf-8") as config_file:
    print(json.load(config_file).get("port", 8085))
PY
)

sudo mkdir -p "$DATA_DIR/jobs" "$DATA_DIR/staging" "$DATA_DIR/generated" "$BACKUP_DIR"
sudo chown -R "$SERVICE_USER":"$SERVICE_USER" "$BASE" "$DATA_DIR" "$BACKUP_DIR"
sudo chown root:"$SERVICE_USER" "$CONFIG_DIR" "$PATHS_FILE"
sudo chmod 0750 "$CONFIG_DIR"
sudo chmod 0644 "$PATHS_FILE"
echo "Configuring Web UI credentials"
if [[ "$EUID" -eq 0 ]]; then
    "$BASE/venv/bin/python" "$BASE/installer/configure_auth.py" \
        --config "$CONF" --secrets "$CONFIG_DIR/secrets.env"
else
    sudo "$BASE/venv/bin/python" "$BASE/installer/configure_auth.py" \
        --config "$CONF" --secrets "$CONFIG_DIR/secrets.env"
fi
sudo chown root:"$SERVICE_USER" "$CONF" "$CONFIG_DIR/secrets.env"
sudo chmod 0640 "$CONF" "$CONFIG_DIR/secrets.env"

if ! getent group openhab >/dev/null 2>&1; then
    sudo groupadd openhab
fi
sudo usermod -a -G openhab "$SERVICE_USER"
echo "Restricting OpenHAB writes to generated output files"
sudo "$BASE/venv/bin/python" "$BASE/installer/provision_managed_files.py" \
    --service-user "$SERVICE_USER" --openhab-group openhab

echo "Installing restricted sudoers policy for service operations"
sudo bash "$BASE/installer/migrate_sudoers.sh"

echo "Installing systemd launch helpers"
sudo install -d -o root -g root -m 0755 /usr/local/libexec/knx_to_openhab
sudo install -o root -g root -m 0755 "$BASE/installer/launch_web.sh" \
    /usr/local/libexec/knx_to_openhab/launch_web.sh
sudo install -o root -g root -m 0755 "$BASE/installer/launch_backup_cleanup.sh" \
    /usr/local/libexec/knx_to_openhab/launch_backup_cleanup.sh
sudo install -o root -g root -m 0755 "$BASE/installer/set_ui_password.py" \
    /usr/local/libexec/knx_to_openhab/set_ui_password.py

echo "Installing systemd units and timers"
sudo install -o root -g root -m 0644 "$BASE/installer/knxohui.service" \
    /etc/systemd/system/knxohui.service
sudo install -o root -g root -m 0644 "$BASE/installer/knxohui-backup-cleanup.service" \
    /etc/systemd/system/knxohui-backup-cleanup.service
sudo install -o root -g root -m 0644 "$BASE/installer/knxohui-backup-cleanup.timer" \
    /etc/systemd/system/knxohui-backup-cleanup.timer
sudo systemctl daemon-reload
sudo systemctl enable knxohui.service
sudo systemctl restart knxohui.service
sudo systemctl enable --now knxohui-backup-cleanup.timer
SETUP_COMPLETED=1

echo "Installation complete. Web UI: http://127.0.0.1:$PORT"
