#!/usr/bin/env bash
set -euo pipefail

INSTALL_DIR="${KNXOH_INSTALL_DIR:-}"
DATA_DIR="${KNXOH_DATA_DIR:-}"
PATHS_FILE="${KNXOH_PATHS_FILE:-/etc/knx_to_openhab/paths.env}"
EXPECTED_RELEASE="${KNXOH_EXPECTED_RELEASE:-}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

fail() {
    printf 'ERROR: %s\n' "$1" >&2
    exit 1
}

if [[ ! -f "$SCRIPT_DIR/maintenance_lock.sh" ]]; then
    fail "The maintenance lock helper is missing."
fi
source "$SCRIPT_DIR/maintenance_lock.sh"
if [[ "${KNXOH_SETUP_LOCK_HELD:-0}" != 1 ]] && ! acquire_maintenance_shared_lock; then
    fail "Setup or uninstall is in progress; retry environment repair later."
fi

if [[ -z "$INSTALL_DIR" || "$INSTALL_DIR" != /* ]]; then
    fail "The installation directory must be provided as an absolute path."
fi
if [[ -z "$DATA_DIR" || "$DATA_DIR" != /* ]]; then
    fail "The runtime-data directory must be provided as an absolute path."
fi
if [[ -z "$EXPECTED_RELEASE" || "$EXPECTED_RELEASE" != /* ]]; then
    fail "The expected active release must be provided as an absolute path."
fi
if [[ "$PATHS_FILE" != /* || ! -f "$PATHS_FILE" || -L "$PATHS_FILE" ]]; then
    fail "The installer paths file is missing or unsafe: $PATHS_FILE"
fi
if [[ ! -f "$INSTALL_DIR/knxoh_paths.py" || -L "$INSTALL_DIR/knxoh_paths.py" ]]; then
    fail "The stable installation is missing its path helper."
fi

if ! RESOLVED_PATHS=$(KNXOH_INSTALL_DIR="$INSTALL_DIR" \
    KNXOH_DATA_DIR="$DATA_DIR" KNXOH_PATHS_FILE="$PATHS_FILE" \
    PYTHONPATH="$INSTALL_DIR" python3 - <<'PY'
import sys

from knxoh_paths import get_paths

paths = get_paths()
print(paths.install_dir)
print(paths.data_dir)
PY
); then
    fail "Could not resolve the installed application and runtime-data paths."
fi
mapfile -t PATH_VALUES <<<"$RESOLVED_PATHS"
if (( ${#PATH_VALUES[@]} != 2 )); then
    fail "The installed application and runtime-data paths are invalid."
fi
RESOLVED_INSTALL_DIR="${PATH_VALUES[0]}"
RESOLVED_DATA_DIR="${PATH_VALUES[1]}"
if [[ "$RESOLVED_INSTALL_DIR" != "$INSTALL_DIR" || "$RESOLVED_DATA_DIR" != "$DATA_DIR" ]]; then
    fail "The supplied install/data paths do not match the configured paths file."
fi

CURRENT_LINK="$INSTALL_DIR/current"
if [[ ! -d "$DATA_DIR" ]]; then
    fail "The configured runtime-data directory does not exist: $DATA_DIR"
fi
UPDATE_LOCK_FILE="$DATA_DIR/updater.lock"
if [[ -L "$UPDATE_LOCK_FILE" || ( -e "$UPDATE_LOCK_FILE" && ! -f "$UPDATE_LOCK_FILE" ) ]]; then
    fail "The updater lock path is not a regular file: $UPDATE_LOCK_FILE"
fi
if ! exec 9>>"$UPDATE_LOCK_FILE"; then
    fail "Could not open the updater lock: $UPDATE_LOCK_FILE"
fi
if ! flock -n 9; then
    fail "An updater is running; retry environment repair after it finishes."
fi

if [[ ! -L "$CURRENT_LINK" ]]; then
    fail "The installation has no active transactional release."
fi
if ! CURRENT_RELEASE=$(readlink -f -- "$CURRENT_LINK"); then
    fail "Could not resolve the active release link."
fi
if ! EXPECTED_RELEASE=$(readlink -f -- "$EXPECTED_RELEASE"); then
    fail "Could not resolve the expected active release."
fi
case "$CURRENT_RELEASE" in
    "$INSTALL_DIR"/releases/*) ;;
    *) fail "The active release target is outside the installation releases directory." ;;
esac
case "$EXPECTED_RELEASE" in
    "$INSTALL_DIR"/releases/*) ;;
    *) fail "The expected release is outside the installation releases directory." ;;
esac
if [[ ! -d "$CURRENT_RELEASE" ]]; then
    fail "The active release directory is missing: $CURRENT_RELEASE"
fi
if [[ "$CURRENT_RELEASE" != "$EXPECTED_RELEASE" ]]; then
    fail "This release is no longer the active current release."
fi
APP_DIR="$CURRENT_RELEASE"

REQUIREMENTS_FILE="$APP_DIR/requirements.txt"
if [[ ! -f "$REQUIREMENTS_FILE" || -L "$REQUIREMENTS_FILE" ]]; then
    fail "The active release requirements file is missing or unsafe."
fi

VENV_DIR="$APP_DIR/venv"
if [[ -L "$VENV_DIR" || ( -e "$VENV_DIR" && ! -d "$VENV_DIR" ) ]]; then
    fail "The active release venv path is not a regular directory."
fi
if [[ -x "$VENV_DIR/bin/python" ]] && \
    PYTHONPATH="$APP_DIR" "$VENV_DIR/bin/python" -c \
        'import knxoh_paths; from web_ui.backend.auth import is_password_hash' \
        >/dev/null 2>&1; then
    printf 'The active release Python environment is already usable.\n'
    exit 0
fi

PREVIOUS_VENV="$APP_DIR/.venv-repair-backup-$$"
if [[ -e "$PREVIOUS_VENV" || -L "$PREVIOUS_VENV" ]]; then
    fail "A previous venv repair backup already exists: $PREVIOUS_VENV"
fi
HAD_PREVIOUS_VENV=0
NEW_VENV_STARTED=0

restore_venv_on_exit() {
    local exit_status=$?
    trap - EXIT
    if (( exit_status != 0 )); then
        if (( NEW_VENV_STARTED )) && [[ -e "$VENV_DIR" || -L "$VENV_DIR" ]]; then
            if ! rm -rf -- "$VENV_DIR"; then
                printf 'ERROR: Could not remove the incomplete venv: %s\n' "$VENV_DIR" >&2
            fi
        fi
        if (( HAD_PREVIOUS_VENV )); then
            if ! mv -- "$PREVIOUS_VENV" "$VENV_DIR"; then
                printf 'ERROR: Could not restore the previous venv from %s\n' \
                    "$PREVIOUS_VENV" >&2
            fi
        fi
    elif (( HAD_PREVIOUS_VENV )); then
        if ! rm -rf -- "$PREVIOUS_VENV"; then
            printf 'WARNING: Could not remove the previous venv backup: %s\n' \
                "$PREVIOUS_VENV" >&2
        fi
    fi
    return "$exit_status"
}
trap restore_venv_on_exit EXIT

if [[ -e "$VENV_DIR" ]]; then
    if ! mv -- "$VENV_DIR" "$PREVIOUS_VENV"; then
        fail "Could not preserve the previous venv before repair."
    fi
    HAD_PREVIOUS_VENV=1
fi

NEW_VENV_STARTED=1
if ! python3 -m venv "$VENV_DIR"; then
    fail "Could not create a new venv at the active release path."
fi
if [[ ! -x "$VENV_DIR/bin/python" || ! -x "$VENV_DIR/bin/pip" ]]; then
    fail "The new venv is missing its Python or pip executable."
fi
if ! "$VENV_DIR/bin/pip" install --disable-pip-version-check \
    -r "$REQUIREMENTS_FILE" -q; then
    fail "Could not install the active release Python requirements."
fi
if ! "$VENV_DIR/bin/pip" check; then
    fail "The repaired Python environment has inconsistent dependencies."
fi
if ! PYTHONPATH="$APP_DIR" "$VENV_DIR/bin/python" -c \
    'import knxoh_paths; from web_ui.backend.auth import is_password_hash'; then
    fail "The repaired Python environment cannot import required release modules."
fi

printf 'Repaired the Python environment for active release %s.\n' "$APP_DIR"
