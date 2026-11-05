#!/usr/bin/env bash
set -euo pipefail

# KNXOH_BOOT_RECOVERY_VERSION=1

fail_startup() {
    echo "KNX to openHAB Web UI startup error: $*" >&2
    exit 1
}

INSTALL_DIR="${KNXOH_INSTALL_DIR:-/opt/knx_to_openhab}"
if [[ "$INSTALL_DIR" != /* ]] || ! INSTALL_DIR=$(cd -P -- "$INSTALL_DIR" && pwd); then
    fail_startup "installation directory must exist and be an absolute path: $INSTALL_DIR"
fi

DATA_DIR="${KNXOH_DATA_DIR:-}"
if [[ -z "$DATA_DIR" || "$DATA_DIR" != /* ]]; then
    fail_startup "KNXOH_DATA_DIR must be configured as an absolute path"
fi
if [[ ! -d "$DATA_DIR" || -L "$DATA_DIR" ]]; then
    fail_startup "runtime-data directory is missing or unsafe: $DATA_DIR"
fi
if ! command -v flock >/dev/null 2>&1; then
    fail_startup "the 'flock' utility is required for release recovery"
fi

UPDATE_LOCK_FILE="$DATA_DIR/updater.lock"
if [[ -L "$UPDATE_LOCK_FILE" || ( -e "$UPDATE_LOCK_FILE" && ! -f "$UPDATE_LOCK_FILE" ) ]]; then
    fail_startup "update-lock path is not a regular file: $UPDATE_LOCK_FILE"
fi
if ! exec {UPDATE_LOCK_FD}>>"$UPDATE_LOCK_FILE"; then
    fail_startup "could not open update-lock file: $UPDATE_LOCK_FILE"
fi

if flock -n "$UPDATE_LOCK_FD"; then
    CURRENT_LINK="$INSTALL_DIR/current"
    if [[ -L "$CURRENT_LINK" ]]; then
        if ! ACTIVE_RELEASE=$(readlink -f -- "$CURRENT_LINK") || [[ ! -d "$ACTIVE_RELEASE" ]]; then
            fail_startup "current release symlink does not resolve to a directory"
        fi

        ACTIVE_MARKER="$ACTIVE_RELEASE/.update-in-progress"
        if [[ -L "$ACTIVE_MARKER" || -e "$ACTIVE_MARKER" ]]; then
            if [[ -L "$ACTIVE_MARKER" || ! -f "$ACTIVE_MARKER" ]]; then
                fail_startup "release recovery marker is not a regular file: $ACTIVE_MARKER"
            fi
            if ! LC_ALL=C tr -d '\000' < "$ACTIVE_MARKER" | cmp -s - "$ACTIVE_MARKER"; then
                fail_startup "release recovery marker contains binary or unreadable data: $ACTIVE_MARKER"
            fi
            RECOVERY_MARKER_LINES=()
            if ! mapfile -t RECOVERY_MARKER_LINES < "$ACTIVE_MARKER"; then
                fail_startup "could not read release recovery marker: $ACTIVE_MARKER"
            fi
            if (( ${#RECOVERY_MARKER_LINES[@]} != 1 )); then
                fail_startup "release recovery marker is empty or malformed: $ACTIVE_MARKER"
            fi
            RECOVERY_TARGET="${RECOVERY_MARKER_LINES[0]}"
            if [[ -z "$RECOVERY_TARGET" || "$RECOVERY_TARGET" == *$'\r'* ]]; then
                fail_startup "release recovery marker is empty or malformed: $ACTIVE_MARKER"
            fi

            if [[ "$RECOVERY_TARGET" == "legacy" ]]; then
                if [[ ! -x "$INSTALL_DIR/venv/bin/gunicorn" ]]; then
                    fail_startup "legacy rollback target is not runnable under $INSTALL_DIR"
                fi
                if ! rm -f -- "$CURRENT_LINK"; then
                    fail_startup "could not restore the legacy installation pointer"
                fi
                echo "Recovered the legacy installation after an interrupted update." >&2
            else
                RELEASES_DIR="$INSTALL_DIR/releases"
                if [[ "$RECOVERY_TARGET" != releases/* || ! -d "$RELEASES_DIR" || \
                    -L "$RELEASES_DIR" ]]; then
                    fail_startup "release recovery marker has an unsafe target: $RECOVERY_TARGET"
                fi
                if ! RECOVERY_RELEASE=$(readlink -f -- "$INSTALL_DIR/$RECOVERY_TARGET") || \
                    [[ ! -d "$RECOVERY_RELEASE" || \
                        "$RECOVERY_RELEASE" != "$RELEASES_DIR/"* || \
                        "$RECOVERY_RELEASE" == "$ACTIVE_RELEASE" ]]; then
                    fail_startup "release recovery target is missing or outside $RELEASES_DIR: $RECOVERY_TARGET"
                fi
                if [[ ! -x "$RECOVERY_RELEASE/venv/bin/gunicorn" ]]; then
                    fail_startup "release recovery target is not runnable: $RECOVERY_RELEASE"
                fi

                TEMP_CURRENT_LINK="$INSTALL_DIR/.current-recovery-$$"
                if [[ -e "$TEMP_CURRENT_LINK" || -L "$TEMP_CURRENT_LINK" ]]; then
                    fail_startup "temporary recovery path already exists: $TEMP_CURRENT_LINK"
                fi
                if ! ln -s -- "$RECOVERY_TARGET" "$TEMP_CURRENT_LINK"; then
                    fail_startup "could not create temporary rollback pointer: $TEMP_CURRENT_LINK"
                fi
                if ! mv -Tf -- "$TEMP_CURRENT_LINK" "$CURRENT_LINK"; then
                    rm -f -- "$TEMP_CURRENT_LINK"
                    fail_startup "could not atomically restore the previous release pointer"
                fi
                echo "Recovered the previous release after an interrupted update." >&2
            fi
        fi
    fi

    if ! flock -u "$UPDATE_LOCK_FD"; then
        fail_startup "could not release update lock: $UPDATE_LOCK_FILE"
    fi
    exec {UPDATE_LOCK_FD}>&-
else
    LOCK_STATUS=$?
    exec {UPDATE_LOCK_FD}>&-
    if (( LOCK_STATUS != 1 )); then
        fail_startup "could not acquire update lock: $UPDATE_LOCK_FILE (flock status $LOCK_STATUS)"
    fi
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
