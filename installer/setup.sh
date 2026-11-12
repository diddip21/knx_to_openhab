#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PATHS_FILE="${KNXOH_PATHS_FILE:-/etc/knx_to_openhab/paths.env}"
if ! python3 - "$PATHS_FILE" <<'PY'
import shlex
import stat
import sys
from pathlib import Path

raw_path = sys.argv[1]
path = Path(raw_path)
managed_header = "# Managed by installer/setup.sh; do not edit by hand."
legacy_keys = {
    "KNXOH_INSTALL_DIR",
    "KNXOH_CONFIG_DIR",
    "KNXOH_DATA_DIR",
    "KNXOH_BACKUP_DIR",
    "KNXOH_MAINTENANCE_LOCK_FILE",
}


def reject(reason):
    print(f"ERROR: {reason}", file=sys.stderr)
    raise SystemExit(1)


if (
    not path.is_absolute()
    or path.parent == Path("/")
    or any(part in {".", ".."} for part in raw_path.split("/"))
    or any(ord(character) < 32 or ord(character) == 127 for character in raw_path)
):
    reject("KNXOH_PATHS_FILE must be a dedicated absolute registry file")

# Root-owned, non-writable parents prevent an unprivileged process from swapping
# a validated registry for a symlink before the later atomic replacement/chown.
protected_parent = False
for parent in path.parents:
    try:
        metadata = parent.lstat()
    except FileNotFoundError:
        continue
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        reject("The paths registry must not have symlinked or non-directory parents")
    if metadata.st_uid != 0:
        reject(f"The paths registry has an untrusted writable ancestor: {parent}")
    mode = stat.S_IMODE(metadata.st_mode)
    writable = mode & (stat.S_IWGRP | stat.S_IWOTH)
    sticky = mode & stat.S_ISVTX
    if writable and not (sticky and protected_parent):
        reject(f"The paths registry has an untrusted writable ancestor: {parent}")
    if not writable:
        protected_parent = True

if path.is_symlink():
    reject("The paths registry must not be a symlink")
try:
    registry_metadata = path.lstat()
except FileNotFoundError:
    registry_metadata = None
if registry_metadata is not None:
    if not stat.S_ISREG(registry_metadata.st_mode):
        reject("The existing paths registry is not a regular file")
    if registry_metadata.st_uid != 0 or registry_metadata.st_mode & (
        stat.S_IWGRP | stat.S_IWOTH
    ):
        reject("The existing paths registry is an untrusted registry file")
    try:
        with path.open(encoding="utf-8") as registry:
            header = registry.readline().rstrip("\r\n")
    except (OSError, UnicodeError) as error:
        reject(f"The existing paths registry cannot be validated: {error}")
    if header != managed_header:
        # Older setup versions wrote the same path assignments without a marker.
        # Accept only that known data format; never treat an arbitrary file as a
        # registry simply because the administrator supplied its path.
        try:
            with path.open(encoding="utf-8") as registry:
                seen = set()
                for raw_line in registry:
                    line = raw_line.strip()
                    if not line or line.startswith("#"):
                        continue
                    name, separator, value = line.partition("=")
                    if not separator or name not in legacy_keys or name in seen:
                        reject("The existing paths registry is not a recognized legacy registry")
                    parsed = shlex.split(value, posix=True)
                    if len(parsed) != 1 or not Path(parsed[0]).is_absolute():
                        reject("The existing paths registry is not a recognized legacy registry")
                    seen.add(name)
        except (OSError, UnicodeError, ValueError) as error:
            reject(f"The existing paths registry is not a recognized legacy registry: {error}")
        if not {"KNXOH_INSTALL_DIR", "KNXOH_CONFIG_DIR"}.issubset(seen):
            reject("The existing paths registry is not a recognized legacy registry")
PY
then
    exit 2
fi
export KNXOH_PATHS_FILE="$PATHS_FILE"
SERVICE_USER="knxohui"
source "$SCRIPT_DIR/maintenance_lock.sh"
if ! resolve_maintenance_lock_path "$PATHS_FILE" allow-initial; then
    exit 2
fi

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

SAVED_MAINTENANCE_LOCK_FILE="$(read_saved_path KNXOH_MAINTENANCE_LOCK_FILE "")"
DEFAULT_MAINTENANCE_LOCK_FILE="/run/lock/knx_to_openhab/maintenance.lock"
if [[ -n "${KNXOH_MAINTENANCE_LOCK_FILE:-}" && \
    -z "$SAVED_MAINTENANCE_LOCK_FILE" && -f "$PATHS_FILE" && \
    "$KNXOH_MAINTENANCE_LOCK_FILE" != "$DEFAULT_MAINTENANCE_LOCK_FILE" ]]; then
    echo "ERROR: A custom maintenance lock cannot be selected while migrating a legacy paths.env. Run setup once with the default lock path first." >&2
    exit 2
fi
if [[ -n "${KNXOH_MAINTENANCE_LOCK_FILE:-}" && \
    -n "$SAVED_MAINTENANCE_LOCK_FILE" && \
    "$KNXOH_MAINTENANCE_LOCK_FILE" != "$SAVED_MAINTENANCE_LOCK_FILE" ]]; then
    echo "ERROR: The configured maintenance lock path cannot change during setup." >&2
    exit 2
fi
KNXOH_MAINTENANCE_LOCK_FILE="${KNXOH_MAINTENANCE_LOCK_FILE:-${SAVED_MAINTENANCE_LOCK_FILE:-$DEFAULT_MAINTENANCE_LOCK_FILE}}"
if ! python3 - "$KNXOH_MAINTENANCE_LOCK_FILE" <<'PY'
import sys
from pathlib import Path

path = Path(sys.argv[1])
if (
    not path.is_absolute()
    or path.name in {"", ".", ".."}
    or path.parent == Path("/")
    or any(part in {".", ".."} for part in path.parts)
    or any(ord(character) < 32 or ord(character) == 127 for character in str(path))
):
    raise SystemExit(1)
PY
then
    echo "ERROR: The maintenance lock path must be a safe absolute file path." >&2
    exit 2
fi
export KNXOH_MAINTENANCE_LOCK_FILE
source "$SCRIPT_DIR/setup_maintenance.sh"
source "$SCRIPT_DIR/setup_systemd_unit.sh"

BASE="${KNXOH_INSTALL_DIR:-$(read_saved_path KNXOH_INSTALL_DIR /opt/knx_to_openhab)}"
CONFIG_DIR="${KNXOH_CONFIG_DIR:-$(read_saved_path KNXOH_CONFIG_DIR /etc/knx_to_openhab)}"
SAVED_DATA_DIR="$(read_saved_path KNXOH_DATA_DIR /var/lib/knx_to_openhab)"
DATA_DIR="${KNXOH_DATA_DIR:-$SAVED_DATA_DIR}"
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
SAVED_DATA_DIR="$(python3 - "$SAVED_DATA_DIR" <<'PY'
import sys
from pathlib import Path

path = Path(sys.argv[1]).expanduser()
if not path.is_absolute():
    raise SystemExit("The previously configured runtime-data path is not absolute")
path = path.resolve()
if path == Path(path.anchor) or str(path) in {"/etc", "/var", "/usr", "/opt", "/home", "/root", "/tmp"}:
    raise SystemExit(f"Refusing an unsafe previously configured runtime-data path: {path}")
print(path)
PY
)" || exit 2

if ! validate_maintenance_lock_location \
    "$SERVICE_USER" "$BASE" "$CONFIG_DIR" "$DATA_DIR" "$BACKUP_DIR"; then
    exit 2
fi

echo "Using application directory: $BASE"
echo "Using configuration directory: $CONFIG_DIR"
echo "Using runtime data directory: $DATA_DIR"
echo "Using backup directory: $BACKUP_DIR"

AUTH_PREFLIGHT_CONFIG="$CONFIG_DIR/config.json"
if [[ ! -f "$AUTH_PREFLIGHT_CONFIG" && -f "$BASE/web_ui/backend/config.json" ]]; then
    AUTH_PREFLIGHT_CONFIG="$BASE/web_ui/backend/config.json"
elif [[ ! -f "$AUTH_PREFLIGHT_CONFIG" && -f "$REPO_ROOT/web_ui/backend/config.json" ]]; then
    AUTH_PREFLIGHT_CONFIG="$REPO_ROOT/web_ui/backend/config.json"
fi
AUTH_PREFLIGHT_STATUS=3
if [[ -x "$BASE/venv/bin/python" ]]; then
    if [[ "$EUID" -eq 0 ]]; then
        AUTH_PREFLIGHT_COMMAND=(env "PYTHONPATH=$BASE" "$BASE/venv/bin/python")
    elif id -u "$SERVICE_USER" >/dev/null 2>&1; then
        AUTH_PREFLIGHT_COMMAND=(sudo -u "$SERVICE_USER" env "PYTHONPATH=$BASE" "$BASE/venv/bin/python")
    else
        AUTH_PREFLIGHT_COMMAND=(env "PYTHONPATH=$BASE" "$BASE/venv/bin/python")
    fi
    if "${AUTH_PREFLIGHT_COMMAND[@]}" - "$AUTH_PREFLIGHT_CONFIG" "$CONFIG_DIR/secrets.env" <<'PY'
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
    if authentication_enabled is False:
        raise SystemExit(0)
    raise SystemExit(1)
legacy_password = auth.get("password", auth.get("legacy_password"))
if legacy_password is not None and str(legacy_password) != "logihome":
    raise SystemExit(0)
if authentication_enabled is False:
    raise SystemExit(0)
if legacy_password is not None:
    raise SystemExit(1)
raise SystemExit(3)
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
if [[ "$AUTH_PREFLIGHT_STATUS" -eq 1 || "$AUTH_PREFLIGHT_STATUS" -eq 3 ]]; then
    echo "If no usable Web UI password is configured, setup will generate one and show it once."
fi

if ! getent group "$SERVICE_USER" >/dev/null 2>&1; then
    sudo groupadd -r "$SERVICE_USER"
fi
if ! id -u "$SERVICE_USER" >/dev/null 2>&1; then
    sudo useradd -r -g "$SERVICE_USER" -s /usr/sbin/nologin "$SERVICE_USER"
fi
sudo env "KNXOH_MAINTENANCE_LOCK_FILE=$KNXOH_MAINTENANCE_LOCK_FILE" \
    bash -c 'source "$1/maintenance_lock.sh"; ensure_maintenance_lock "$2"' \
    _ "$SCRIPT_DIR" "$SERVICE_USER"

PREVIOUSLY_ACTIVE_UNITS=()
for unit in knxohui-backup-cleanup.timer knxohui-backup-cleanup.service knxohui.service; do
    if sudo systemctl is-active --quiet "$unit"; then
        PREVIOUSLY_ACTIVE_UNITS+=("$unit")
    fi
done
SETUP_COMPLETED=0

quiesce_setup_services() {
    sudo bash "$REPO_ROOT/installer/quiesce_systemd_unit.sh" knxohui-backup-cleanup.timer || return
    sudo bash "$REPO_ROOT/installer/quiesce_systemd_unit.sh" knxohui-backup-cleanup.service || return
    sudo bash "$REPO_ROOT/installer/quiesce_systemd_unit.sh" knxohui.service || return
    sudo bash "$REPO_ROOT/installer/quiesce_update_service.sh" || return
    sudo bash "$REPO_ROOT/installer/quiesce_systemd_unit.sh" knxohui-backup-cleanup.timer || return
    sudo bash "$REPO_ROOT/installer/quiesce_systemd_unit.sh" knxohui-backup-cleanup.service || return
    sudo bash "$REPO_ROOT/installer/quiesce_systemd_unit.sh" knxohui.service
}

restore_previous_services() {
    local exit_status=$?
    trap - EXIT
    release_setup_updater_locks || echo "Could not release setup updater locks." >&2
    if ! release_maintenance_lock; then
        echo "Could not release the setup maintenance lock." >&2
    fi
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
echo "Stopping services and waiting for the updater to finish"
quiesce_setup_services
echo "Acquiring exclusive maintenance lock and rechecking systemd state"
acquire_setup_maintenance_lock quiesce_setup_services

UPDATER_LOCK_PATHS=("$SAVED_DATA_DIR/updater.lock")
if [[ "$DATA_DIR" != "$SAVED_DATA_DIR" ]]; then
    UPDATER_LOCK_PATHS+=("$DATA_DIR/updater.lock")
fi
for updater_data_dir in "$SAVED_DATA_DIR" "$DATA_DIR"; do
    if [[ ! -d "$updater_data_dir" ]]; then
        sudo install -d -o "$SERVICE_USER" -g "$SERVICE_USER" -m 0750 "$updater_data_dir"
    fi
done
echo "Acquiring legacy updater locks for the saved and selected runtime-data paths"
acquire_setup_updater_locks "$SERVICE_USER" "${UPDATER_LOCK_PATHS[@]}"

echo "Installing lock-aware stable service launch helpers"
sudo install -d -o root -g root -m 0755 /usr/local/libexec/knx_to_openhab
sudo install -o root -g root -m 0755 "$REPO_ROOT/installer/maintenance_lock.sh" \
    /usr/local/libexec/knx_to_openhab/maintenance_lock.sh
sudo install -o root -g root -m 0755 "$REPO_ROOT/installer/launch_web.sh" \
    /usr/local/libexec/knx_to_openhab/launch_web.sh
sudo install -o root -g root -m 0755 "$REPO_ROOT/installer/launch_backup_cleanup.sh" \
    /usr/local/libexec/knx_to_openhab/launch_backup_cleanup.sh
sudo install -o root -g root -m 0755 "$REPO_ROOT/installer/launch_update.sh" \
    /usr/local/libexec/knx_to_openhab/launch_update.sh
sudo install -o root -g root -m 0755 "$REPO_ROOT/installer/repair_release_venv.sh" \
    /usr/local/libexec/knx_to_openhab/repair_release_venv.sh
sudo install -o root -g root -m 0755 "$REPO_ROOT/installer/hold_updater_locks.sh" \
    /usr/local/libexec/knx_to_openhab/hold_updater_locks.sh
sudo install -o root -g root -m 0755 "$REPO_ROOT/installer/quiesce_systemd_unit.sh" \
    /usr/local/libexec/knx_to_openhab/quiesce_systemd_unit.sh
sudo install -o root -g root -m 0644 "$REPO_ROOT/installer/uninstall_unit_files.sh" \
    /usr/local/libexec/knx_to_openhab/uninstall_unit_files.sh
sudo install -d -o root -g root -m 0755 /etc/tmpfiles.d
sudo python3 "$REPO_ROOT/installer/write_maintenance_lock_tmpfiles.py" \
    "$KNXOH_MAINTENANCE_LOCK_FILE" /etc/tmpfiles.d/knx_to_openhab.conf \
    "$BASE" "$CONFIG_DIR" "$DATA_DIR" "$BACKUP_DIR"
sudo systemd-tmpfiles --create /etc/tmpfiles.d/knx_to_openhab.conf
echo "Rechecking service quiescence after replacing legacy launch helpers"
quiesce_setup_services

sudo mkdir -p "$BASE"
sudo chown "$SERVICE_USER":"$SERVICE_USER" "$BASE"

sudo python3 -m venv "$BASE/venv"
sudo "$BASE/venv/bin/pip" install --upgrade pip
sudo "$BASE/venv/bin/pip" install -r "$REPO_ROOT/requirements.txt"

echo "Installing application files while preserving runtime configuration"
sudo rsync -a --exclude .git --exclude /venv --exclude /config.json \
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
    "$REPO_ROOT/installer/provision_managed_outputs.py" \
    /usr/local/libexec/knx_to_openhab/provision_managed_outputs.py

echo "Migrating configuration, jobs, staging data and backups"
sudo "$BASE/venv/bin/python" "$BASE/installer/migrate_runtime_data.py" \
    --source-root "$BASE" \
    --template-root "$REPO_ROOT" \
    --config-dir "$CONFIG_DIR" \
    --data-dir "$DATA_DIR" \
    --backup-dir "$BACKUP_DIR" \
    --install-dir "$BASE" \
    --paths-file "$PATHS_FILE" \
    --maintenance-lock-file "$KNXOH_MAINTENANCE_LOCK_FILE"

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
sudo install -o root -g root -m 0755 "$REPO_ROOT/installer/set_ui_password.py" \
    /usr/local/libexec/knx_to_openhab/set_ui_password.py

if [[ -L "$BASE/current" ]]; then
    if ! ACTIVE_RELEASE=$(readlink -f -- "$BASE/current"); then
        echo "The active release link could not be resolved: $BASE/current" >&2
        exit 1
    fi
    case "$ACTIVE_RELEASE" in
        "$BASE"/releases/*) ;;
        *)
            echo "The active release link points outside $BASE/releases: $ACTIVE_RELEASE" >&2
            exit 1
            ;;
    esac
    if [[ ! -d "$ACTIVE_RELEASE" ]]; then
        echo "The active release directory is missing: $ACTIVE_RELEASE" >&2
        exit 1
    fi
    echo "Repairing the active release Python environment before restarting the Web UI"
    sudo -u "$SERVICE_USER" env \
        "KNXOH_INSTALL_DIR=$BASE" \
        "KNXOH_DATA_DIR=$DATA_DIR" \
        "KNXOH_PATHS_FILE=$PATHS_FILE" \
        "KNXOH_EXPECTED_RELEASE=$ACTIVE_RELEASE" \
        "KNXOH_SETUP_LOCK_HELD=1" \
        "KNXOH_SETUP_UPDATER_LOCK_HELD=1" \
        bash /usr/local/libexec/knx_to_openhab/repair_release_venv.sh
fi

echo "Installing systemd units and timers"
install_setup_systemd_unit "$REPO_ROOT/installer/knxohui.service" \
    /etc/systemd/system/knxohui.service knxohui.service "$PATHS_FILE"
install_setup_systemd_unit "$REPO_ROOT/installer/knxohui-update.service" \
    /etc/systemd/system/knxohui-update.service knxohui-update.service "$PATHS_FILE"
install_setup_systemd_unit "$REPO_ROOT/installer/knxohui-backup-cleanup.service" \
    /etc/systemd/system/knxohui-backup-cleanup.service knxohui-backup-cleanup.service "$PATHS_FILE"
install_setup_systemd_unit "$REPO_ROOT/installer/knxohui-backup-cleanup.timer" \
    /etc/systemd/system/knxohui-backup-cleanup.timer knxohui-backup-cleanup.timer "$PATHS_FILE"
sudo systemctl daemon-reload
setup_systemctl_if_unmasked knxohui.service enable
setup_systemctl_if_unmasked knxohui-backup-cleanup.timer enable
release_setup_updater_locks
release_maintenance_lock
setup_systemctl_if_unmasked knxohui.service restart
setup_systemctl_if_unmasked knxohui-backup-cleanup.timer start
SETUP_COMPLETED=1

echo "Installation complete. Web UI: http://127.0.0.1:$PORT"
