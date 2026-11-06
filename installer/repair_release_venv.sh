#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
APP_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd -P)"

fail() {
    printf 'ERROR: %s\n' "$1" >&2
    exit 1
}

if [[ ! -f "$APP_DIR/knxoh_paths.py" || -L "$APP_DIR/knxoh_paths.py" ]]; then
    fail "The active release is missing its path helper."
fi

if ! RESOLVED_PATHS=$(PYTHONPATH="$APP_DIR" python3 - "$APP_DIR" <<'PY'
import sys

from knxoh_paths import get_paths

paths = get_paths(sys.argv[1])
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
INSTALL_DIR="${PATH_VALUES[0]}"
DATA_DIR="${PATH_VALUES[1]}"
if [[ "$INSTALL_DIR" != /* || "$DATA_DIR" != /* ]]; then
    fail "The installed application and runtime-data paths must be absolute."
fi

case "$APP_DIR" in
    "$INSTALL_DIR"/releases/*) ;;
    *) fail "The repair target is not under the installation releases directory." ;;
esac

CURRENT_LINK="$INSTALL_DIR/current"
if [[ ! -L "$CURRENT_LINK" ]]; then
    fail "The installation has no active transactional release."
fi
if ! CURRENT_RELEASE=$(readlink -f -- "$CURRENT_LINK"); then
    fail "Could not resolve the active release link."
fi
if [[ "$CURRENT_RELEASE" != "$APP_DIR" ]]; then
    fail "This release is no longer the active current release."
fi

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
