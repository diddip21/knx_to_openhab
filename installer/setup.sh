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
    --exclude /web_ui/backend/config.json "$REPO_ROOT/" "$BASE/"
if [[ ! -f "$BASE/config.json" ]]; then
    sudo install -o "$SERVICE_USER" -g "$SERVICE_USER" -m 0640 \
        "$REPO_ROOT/config.json" "$BASE/config.json"
fi

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
sudo "$BASE/venv/bin/python" "$BASE/installer/configure_auth.py" \
    --config "$CONF" --secrets "$CONFIG_DIR/secrets.env"
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

echo "Installation complete. Web UI: http://127.0.0.1:$PORT"
