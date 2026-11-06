#!/usr/bin/env bash
# Self-update script for KNX to OpenHAB Generator
# This script is executed by the web UI when an update is requested

set -euo pipefail

# Configuration
# Resolve installation directory dynamically (can be overridden via INSTALL_DIR env var)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="${KNXOH_INSTALL_DIR:-${INSTALL_DIR:-$SCRIPT_DIR}}"
LOG_FILE="${LOG_FILE:-/var/log/knx_to_openhab_update.log}"
SERVICE_NAME="knxohui.service"
RELEASE_TAG="${RELEASE_TAG:-}"
RELEASE_COMMIT_HASH="${RELEASE_COMMIT_HASH:-}"
RELEASE_COMMIT_DATE="${RELEASE_COMMIT_DATE:-}"
RELEASE_COMMIT_MESSAGE="${RELEASE_COMMIT_MESSAGE:-}"
RELEASE_AUTHOR="${RELEASE_AUTHOR:-unknown}"
PATHS_FILE="${KNXOH_PATHS_FILE:-/etc/knx_to_openhab/paths.env}"

# Logging function
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

log "========================================="
log "Starting KNX to OpenHAB Generator update"
log "========================================="

# Change to installation directory
if ! cd "$INSTALL_DIR"; then
    log "ERROR: Failed to change to $INSTALL_DIR"
    exit 1
fi
INSTALL_DIR="$(pwd -P)"

CURRENT_LINK="$INSTALL_DIR/current"
RELEASES_DIR="$INSTALL_DIR/releases"
LEGACY_INSTALL=0
if [[ -L "$CURRENT_LINK" ]]; then
    if ! APP_DIR=$(readlink -f -- "$CURRENT_LINK"); then
        log "ERROR: Could not resolve the active release link."
        exit 1
    fi
    case "$APP_DIR" in
        "$RELEASES_DIR"/*) ;;
        *)
            log "ERROR: The active release link points outside $RELEASES_DIR."
            exit 1
            ;;
    esac
    if [[ ! -d "$APP_DIR" ]]; then
        log "ERROR: The active release is incomplete: $APP_DIR"
        exit 1
    fi
elif [[ -e "$CURRENT_LINK" ]]; then
    log "ERROR: $CURRENT_LINK exists but is not a release symlink."
    exit 1
else
    LEGACY_INSTALL=1
    APP_DIR="$INSTALL_DIR"
fi

printf -v MIGRATE_SUDOERS_RECOVERY_COMMAND 'sudo bash %q' "$APP_DIR/installer/migrate_sudoers.sh"

if [[ ! "$RELEASE_TAG" =~ ^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(\+[0-9A-Za-z-]+(\.[0-9A-Za-z-]+)*)?$ ]]; then
    log "ERROR: A valid stable release tag is required. Trigger the update from the Web UI again."
    exit 1
fi
if [[ -n "${UPDATE_REQUEST_ID:-}" && ! "$UPDATE_REQUEST_ID" =~ ^[0-9a-f]{32}$ ]]; then
    log "ERROR: The update request identifier is invalid."
    exit 1
fi

if [[ -z "${KNXOH_DATA_DIR:-}" ]]; then
    if ! UPDATE_LOCK_DIR=$(KNXOH_INSTALL_DIR="$INSTALL_DIR" \
        KNXOH_PATHS_FILE="$PATHS_FILE" PYTHONPATH="$INSTALL_DIR" \
        python3 -c 'from knxoh_paths import get_paths; print(get_paths().data_dir)'); then
        log "ERROR: Could not resolve the configured runtime-data path for the update lock."
        exit 1
    fi
else
    UPDATE_LOCK_DIR="$KNXOH_DATA_DIR"
fi

if [[ "$UPDATE_LOCK_DIR" != /* ]]; then
    log "ERROR: The update-lock directory must be an absolute path: $UPDATE_LOCK_DIR"
    exit 1
fi
SETUP_CONFIG_DIR="${KNXOH_CONFIG_DIR:-/etc/knx_to_openhab}"
SETUP_BACKUP_DIR="${KNXOH_BACKUP_DIR:-/var/backups/knx_to_openhab}"
if [[ -f "$INSTALL_DIR/knxoh_paths.py" && ! -L "$INSTALL_DIR/knxoh_paths.py" ]]; then
    if ! SETUP_PATHS=$(KNXOH_INSTALL_DIR="$INSTALL_DIR" KNXOH_DATA_DIR="$UPDATE_LOCK_DIR" \
        KNXOH_PATHS_FILE="$PATHS_FILE" PYTHONPATH="$INSTALL_DIR" python3 - <<'PY'
from knxoh_paths import get_paths

paths = get_paths()
print(paths.config_dir)
print(paths.backup_dir)
PY
    ); then
        log "ERROR: Could not resolve configured paths for setup recovery."
        exit 1
    fi
    mapfile -t SETUP_PATH_VALUES <<<"$SETUP_PATHS"
    if (( ${#SETUP_PATH_VALUES[@]} != 2 )); then
        log "ERROR: Configured paths for setup recovery are invalid."
        exit 1
    fi
    SETUP_CONFIG_DIR="${KNXOH_CONFIG_DIR:-${SETUP_PATH_VALUES[0]}}"
    SETUP_BACKUP_DIR="${KNXOH_BACKUP_DIR:-${SETUP_PATH_VALUES[1]}}"
fi
printf -v SETUP_RECOVERY_COMMAND \
    'sudo env KNXOH_INSTALL_DIR=%q KNXOH_CONFIG_DIR=%q KNXOH_DATA_DIR=%q KNXOH_BACKUP_DIR=%q KNXOH_PATHS_FILE=%q bash %q' \
    "$INSTALL_DIR" "$SETUP_CONFIG_DIR" "$UPDATE_LOCK_DIR" "$SETUP_BACKUP_DIR" \
    "$PATHS_FILE" "$APP_DIR/installer/setup.sh"
VENV_REPAIR_HELPER="/usr/local/libexec/knx_to_openhab/repair_release_venv.sh"
printf -v VENV_RECOVERY_COMMAND \
    'sudo -u knxohui env KNXOH_INSTALL_DIR=%q KNXOH_DATA_DIR=%q KNXOH_PATHS_FILE=%q KNXOH_EXPECTED_RELEASE=%q bash %q' \
    "$INSTALL_DIR" "$UPDATE_LOCK_DIR" "$PATHS_FILE" "$APP_DIR" "$VENV_REPAIR_HELPER"
if ! command -v flock >/dev/null 2>&1; then
    log "ERROR: The 'flock' utility is required to prevent concurrent updates."
    exit 1
fi
if ! mkdir -p -- "$UPDATE_LOCK_DIR"; then
    log "ERROR: Could not create update-lock directory: $UPDATE_LOCK_DIR"
    exit 1
fi

UPDATE_LOCK_FILE="$UPDATE_LOCK_DIR/updater.lock"
if [[ -L "$UPDATE_LOCK_FILE" || ( -e "$UPDATE_LOCK_FILE" && ! -f "$UPDATE_LOCK_FILE" ) ]]; then
    log "ERROR: Update-lock path is not a regular file: $UPDATE_LOCK_FILE"
    exit 1
fi
if ! exec 9>>"$UPDATE_LOCK_FILE"; then
    log "ERROR: Could not open update-lock file: $UPDATE_LOCK_FILE"
    exit 1
fi
if ! flock -n 9; then
    log "ERROR: Another KNX to openHAB update is already running. Try again later."
    exit 1
fi
log "Update lock acquired."

# The previous release granted passwordless root Git access. A Web UI update
# cannot safely replace that policy itself, so require the one-time admin
# migration before allowing another update to proceed.
if ! SUDO_POLICY=$(sudo -n -l 2>/dev/null); then
    log "ERROR: Cannot verify the service user's sudoers policy. Run $MIGRATE_SUDOERS_RECOVERY_COMMAND as an administrator, then retry."
    exit 1
fi
if printf '%s\n' "$SUDO_POLICY" | grep -Eq '(/usr/bin/git|/bin/git)[[:space:]]+\\*|NOPASSWD:[[:space:]]+ALL'; then
    log "ERROR: The legacy broad sudoers policy is still installed. Run $MIGRATE_SUDOERS_RECOVERY_COMMAND as an administrator before updating again."
    exit 1
fi

# Refuse an in-place update until credentials live in the external config tree.
# An older checkout may still keep its default or plaintext password in tracked
# files, so fetching first could replace the code before credentials are migrated.
if [[ ! -x "$APP_DIR/venv/bin/python" ]] || \
    ! PYTHONPATH="$APP_DIR" "$APP_DIR/venv/bin/python" -c \
        'import knxoh_paths; from web_ui.backend.auth import is_password_hash' \
        >/dev/null 2>&1; then
    log "ERROR: The active release Python environment is missing or unusable."
    if (( LEGACY_INSTALL )); then
        log "Recovery: run $SETUP_RECOVERY_COMMAND from an interactive SSH terminal (for example, ssh -t), then retry."
    elif [[ -x "$VENV_REPAIR_HELPER" ]]; then
        log "Recovery: run $VENV_RECOVERY_COMMAND from an interactive SSH terminal (for example, ssh -t), then retry."
    else
        log "The stable recovery helper is not installed; setup will install it and repair the active release."
        log "Recovery: run $SETUP_RECOVERY_COMMAND from an interactive SSH terminal (for example, ssh -t), then retry."
    fi
    exit 1
fi
if ! CREDENTIAL_CHECK=$(KNXOH_INSTALL_DIR="$INSTALL_DIR" KNXOH_PATHS_FILE="$PATHS_FILE" \
    PYTHONPATH="$APP_DIR" "$APP_DIR/venv/bin/python" - "$PATHS_FILE" <<'PY' 2>&1
import base64
import binascii
import json
import sys
from pathlib import Path

from knxoh_paths import get_paths
from web_ui.backend.auth import is_password_hash

paths_file = Path(sys.argv[1])
if not paths_file.is_file():
    raise SystemExit(f"installer paths file is missing: {paths_file}")
paths = get_paths()
if (
    paths.secrets_file is None
    or paths.config_dir == paths.install_dir
    or paths.install_dir in paths.config_dir.parents
):
    raise SystemExit("external Web UI configuration is not installed")
if not paths.web_config_file.is_file() or not paths.secrets_file.is_file():
    raise SystemExit("external Web UI config.json or secrets.env is missing")
try:
    config = json.loads(paths.web_config_file.read_text(encoding="utf-8"))
except (OSError, json.JSONDecodeError) as error:
    raise SystemExit(f"cannot read external Web UI config: {error}") from error
try:
    generator_config = json.loads(
        paths.generator_config_file.read_text(encoding="utf-8")
    )
except (OSError, json.JSONDecodeError) as error:
    raise SystemExit(f"cannot read external generator config: {error}") from error
if not isinstance(generator_config, dict):
    raise SystemExit("external generator config must be a JSON object")
auth = config.get("auth", {}) if isinstance(config, dict) else None
if not isinstance(auth, dict):
    raise SystemExit("external Web UI auth configuration is invalid")
if auth.get("enabled", True):
    encoded_hash = None
    for line in paths.secrets_file.read_text(encoding="utf-8").splitlines():
        name, separator, value = line.partition("=")
        if separator and name == "KNXOH_UI_PASSWORD_HASH_B64":
            encoded_hash = value.strip()
    try:
        password_hash = base64.b64decode(encoded_hash, validate=True).decode("utf-8")
    except (TypeError, binascii.Error, UnicodeDecodeError) as error:
        raise SystemExit("a valid external Argon2id password hash is required") from error
    if not is_password_hash(password_hash):
        raise SystemExit("a valid external Argon2id password hash is required")
PY
); then
    log "ERROR: Credential migration is incomplete: $CREDENTIAL_CHECK"
    log "Recovery: run $SETUP_RECOVERY_COMMAND from an interactive SSH terminal (for example, ssh -t), then retry."
    exit 1
fi
log "External Web UI and generator configuration are ready."
log "External Web UI password hash is ready."

# Legacy installations still use a Git checkout as their fallback version, so
# refuse unrelated local edits there. Transactional releases are immutable trees
# under releases/ and need no Git access during an update.
if (( LEGACY_INSTALL )); then
    if [[ ! -w ".git" ]]; then
        log "ERROR: The service user cannot write to $INSTALL_DIR/.git. Run fix_permissions.sh as an administrator."
        exit 1
    fi
    log "Verifying legacy Git installation..."
    if ! git -c "safe.directory=$INSTALL_DIR" rev-parse --git-dir > /dev/null 2>&1; then
        log "ERROR: Not a valid Git installation or access denied."
        exit 1
    fi
    if ! LOCAL_CHANGES=$(git -c "safe.directory=$INSTALL_DIR" status --porcelain --untracked-files=all -- . \
        ':(exclude)update.log' ':(exclude)version.json' \
        ':(exclude,top)config.json' ':(exclude)web_ui/backend/config.json'); then
        log "ERROR: Could not inspect the legacy installation working tree."
        exit 1
    fi
    if [[ -n "$LOCAL_CHANGES" ]]; then
        log "ERROR: Local application changes are present; refusing to update or stash them."
        log "$LOCAL_CHANGES"
        log "Commit or move those files, then retry the update."
        exit 1
    fi
fi

# A selected release must include exact commit metadata from the GitHub API.
if [[ ! "$RELEASE_COMMIT_HASH" =~ ^[0-9a-f]{40}$ ]]; then
    log "ERROR: The selected release commit metadata is missing or invalid. Retry from the Web UI."
    exit 1
fi

# A transactional installation can retry the latest stable release without
# downloading or replacing its active environment.
if [[ -L "$CURRENT_LINK" && -f "$APP_DIR/version.json" && \
    ! -e "$APP_DIR/.update-in-progress" && ! -L "$APP_DIR/.update-in-progress" ]]; then
    if "$APP_DIR/venv/bin/python" - "$APP_DIR/version.json" "$RELEASE_TAG" \
        "$RELEASE_COMMIT_HASH" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as version_file:
    metadata = json.load(version_file)
raise SystemExit(
    0
    if metadata.get("release_tag") == sys.argv[2]
    and metadata.get("commit_hash") == sys.argv[3]
    else 1
)
PY
    then
        log "Already running selected release $RELEASE_TAG."
        exit 0
    fi
fi
if [[ -L "$CURRENT_LINK" && \
    ( -e "$APP_DIR/.update-in-progress" || -L "$APP_DIR/.update-in-progress" ) ]]; then
    log "Detected an interrupted release activation; retrying release validation."
fi

# Snapshot the application and external configuration before any update work.
# The helper publishes only a readable archive, so a failed backup always stops
# before provisioning, downloading, or staging the selected release.
log "Creating and validating pre-update backup..."
if ! BACKUP_PATH=$(KNXOH_INSTALL_DIR="$INSTALL_DIR" KNXOH_PATHS_FILE="$PATHS_FILE" PYTHONPATH="$APP_DIR" "$APP_DIR/venv/bin/python" "$APP_DIR/installer/create_update_backup.py" 2>&1); then
    log "ERROR: Could not create and validate the pre-update backup: $BACKUP_PATH"
    exit 1
fi
log "Backup created and validated: $BACKUP_PATH"

# Provision on each real update before activation. The fixed root helper reads
# its protected config and does not depend on the incoming Git revision.
if ! sudo -n /usr/local/sbin/knxohui-service-update provision-yaml; then
    log "ERROR: Could not provision the configured OpenHAB YAML target."
    log "Run $SETUP_RECOVERY_COMMAND as an administrator, then retry."
    exit 1
fi

if [[ -L "$RELEASES_DIR" ]]; then
    log "ERROR: Refusing a symlinked release directory: $RELEASES_DIR"
    exit 1
fi
if ! mkdir -p -- "$RELEASES_DIR"; then
    log "ERROR: Could not create release directory: $RELEASES_DIR"
    exit 1
fi

active_target_is_within() {
    local candidate_path active_target resolved_candidate recovery_target resolved_recovery
    candidate_path="$1"
    [[ -L "$CURRENT_LINK" ]] || return 1

    # If either path cannot be resolved, preserve the candidate rather than
    # risk deleting the release selected by current.
    if ! active_target=$(readlink -f -- "$CURRENT_LINK") || \
        ! resolved_candidate=$(readlink -f -- "$candidate_path"); then
        return 0
    fi
    if [[ "$active_target" == "$resolved_candidate" || \
        "$active_target" == "$resolved_candidate/"* ]]; then
        return 0
    fi

    # An interrupted active candidate records the pointer needed for rollback.
    # Preserve that target too; otherwise startup cleanup could erase the only
    # known-good release before recovery gets a chance to restore it.
    if [[ -f "$active_target/.update-in-progress" && \
        ! -L "$active_target/.update-in-progress" ]]; then
        recovery_target=$(<"$active_target/.update-in-progress")
        if [[ -n "$recovery_target" && "$recovery_target" != "legacy" ]] && \
            resolved_recovery=$(readlink -f -- "$recovery_target"); then
            [[ "$resolved_recovery" == "$resolved_candidate" || \
                "$resolved_recovery" == "$resolved_candidate/"* ]] && return 0
        fi
    fi
    return 1
}

remove_inactive_release_path() {
    local candidate_path description success_message
    candidate_path="$1"
    description="$2"
    success_message="${3:-Removed $description: $(basename -- "$candidate_path").}"
    [[ -d "$candidate_path" && ! -L "$candidate_path" ]] || return 0
    if active_target_is_within "$candidate_path"; then
        log "Keeping $description because current selects it: $candidate_path"
        return 0
    fi
    if ! rm -rf -- "$candidate_path"; then
        log "ERROR: Could not remove $description: $candidate_path"
        return 1
    fi
    log "$success_message"
}

cleanup_abandoned_release_paths() {
    local stale_path

    # The update lock is already held, so no active updater owns these
    # abandoned direct-child staging directories.
    for stale_path in "$RELEASES_DIR"/.staging-*; do
        [[ -d "$stale_path" && ! -L "$stale_path" ]] || continue
        remove_inactive_release_path "$stale_path" "stale release staging directory" || return 1
    done

    for stale_path in "$RELEASES_DIR"/*; do
        [[ -d "$stale_path" && ! -L "$stale_path" ]] || continue
        [[ -f "$stale_path/.update-in-progress" && ! -L "$stale_path/.update-in-progress" ]] || continue
        remove_inactive_release_path "$stale_path" "abandoned release candidate" || return 1
    done
}

if ! cleanup_abandoned_release_paths; then
    exit 1
fi

RELEASE_DIR_NAME="${RELEASE_TAG#v}-${RELEASE_COMMIT_HASH:0:12}-$(date +%s)-$$"
NEW_RELEASE_DIR="$RELEASES_DIR/$RELEASE_DIR_NAME"
if ! STAGING_DIR=$(mktemp -d "$RELEASES_DIR/.staging-${RELEASE_TAG#v}-XXXXXXXX"); then
    log "ERROR: Could not create a release staging directory."
    exit 1
fi
cleanup_release_staging() {
    if [[ -n "${STAGING_DIR:-}" && -d "$STAGING_DIR" ]]; then
        remove_inactive_release_path "$STAGING_DIR" "release staging directory" || true
    fi
    if [[ "${PRESERVE_RELEASE_CANDIDATE:-0}" != 1 && \
        -d "$NEW_RELEASE_DIR" && ! -L "$NEW_RELEASE_DIR" ]]; then
        remove_inactive_release_path "$NEW_RELEASE_DIR" "unactivated release candidate" || true
    fi
}
RELEASE_ACTIVATED=0
trap cleanup_release_staging EXIT

REPOSITORY="${KNXOH_GITHUB_REPOSITORY:-diddip21/knx_to_openhab}"
log "Downloading and verifying release archive $RELEASE_TAG..."
if ! STAGED_APP_DIR=$(KNXOH_INSTALL_DIR="$INSTALL_DIR" KNXOH_PATHS_FILE="$PATHS_FILE" \
    PYTHONPATH="$APP_DIR" "$APP_DIR/venv/bin/python" \
    "$APP_DIR/installer/prepare_release.py" \
    --repository "$REPOSITORY" --tag "$RELEASE_TAG" --destination "$STAGING_DIR" \
    --commit-hash "$RELEASE_COMMIT_HASH" --commit-date "$RELEASE_COMMIT_DATE" \
    --commit-message "$RELEASE_COMMIT_MESSAGE" --author "$RELEASE_AUTHOR" 2>&1); then
    log "ERROR: Could not download, verify, or extract release $RELEASE_TAG: $STAGED_APP_DIR"
    exit 1
fi
log "Verified release staged at $STAGED_APP_DIR."

if [[ -L "$STAGED_APP_DIR/.update-in-progress" ]] || \
    ! touch -- "$STAGED_APP_DIR/.update-in-progress"; then
    log "ERROR: Could not mark the staged release candidate as in progress."
    exit 1
fi

if ! mv -- "$STAGED_APP_DIR" "$NEW_RELEASE_DIR"; then
    log "ERROR: Could not publish the complete staged release."
    exit 1
fi
rmdir -- "$STAGING_DIR"
STAGING_DIR=""
STAGED_APP_DIR="$NEW_RELEASE_DIR"

log "Creating isolated Python environment for $RELEASE_TAG..."
if ! python3 -m venv "$STAGED_APP_DIR/venv"; then
    log "ERROR: Could not create the release Python environment."
    exit 1
fi
if ! "$STAGED_APP_DIR/venv/bin/pip" install --disable-pip-version-check \
    -r "$STAGED_APP_DIR/requirements.txt" -q; then
    log "ERROR: Could not install dependencies for $RELEASE_TAG. The active release was not changed."
    exit 1
fi
if ! "$STAGED_APP_DIR/venv/bin/pip" check; then
    log "ERROR: The staged release has inconsistent Python dependencies."
    exit 1
fi
if ! "$STAGED_APP_DIR/venv/bin/python" -m compileall -q "$STAGED_APP_DIR"; then
    log "ERROR: Python compilation smoke test failed for $RELEASE_TAG."
    exit 1
fi
if ! PYTHONPATH="$STAGED_APP_DIR" "$STAGED_APP_DIR/venv/bin/python" -c \
    'import flask, gunicorn, requests, xknxproject; import web_ui.backend.updater'; then
    log "ERROR: Python dependency and updater import smoke test failed for $RELEASE_TAG."
    exit 1
fi
log "No release data migration is declared; external configuration and runtime data remain in place."

# Resolve the health-check target from the same normalized settings Gunicorn
# uses. Hostnames must resolve to a local interface address before we probe.
if ! WEB_UI_ENDPOINT=$(KNXOH_INSTALL_DIR="$INSTALL_DIR" KNXOH_PATHS_FILE="$PATHS_FILE" \
    PYTHONPATH="$STAGED_APP_DIR" "$STAGED_APP_DIR/venv/bin/python" - <<'PY'
from installer.web_ui_endpoint import resolve_web_ui_health_endpoint
from web_ui.backend.storage import load_config

config = load_config()
health_host, port = resolve_web_ui_health_endpoint(
    config.get("bind_host", "127.0.0.1"), config.get("port", 8085)
)
print(f"{health_host} {port}")
PY
); then
    log "ERROR: Could not determine a safe Web UI health-check endpoint."
    exit 1
fi
IFS=' ' read -r WEB_UI_HEALTH_HOST WEB_UI_PORT <<< "$WEB_UI_ENDPOINT"

PREVIOUS_LINK=""
PREVIOUS_RELEASE_DIR=""
HAD_PREVIOUS_LINK=0
if [[ -L "$CURRENT_LINK" ]]; then
    CURRENT_ACTIVE_RELEASE=$(readlink -f -- "$CURRENT_LINK")
    CURRENT_MARKER="$CURRENT_ACTIVE_RELEASE/.update-in-progress"
    if [[ -f "$CURRENT_MARKER" && ! -L "$CURRENT_MARKER" ]]; then
        RECOVERY_TARGET=$(<"$CURRENT_MARKER")
        if [[ "$RECOVERY_TARGET" == "legacy" ]]; then
            if [[ ! -x "$INSTALL_DIR/venv/bin/gunicorn" ]]; then
                log "ERROR: Legacy release recovery target is not runnable under $INSTALL_DIR."
                exit 1
            fi
            log "Recovering the legacy installation as the rollback target."
        elif [[ -n "$RECOVERY_TARGET" ]]; then
            if [[ "$RECOVERY_TARGET" != releases/* || ! -d "$RELEASES_DIR" || \
                -L "$RELEASES_DIR" ]]; then
                log "ERROR: Release recovery marker has an unsafe target: $RECOVERY_TARGET"
                exit 1
            fi
            if ! PREVIOUS_RELEASE_DIR=$(readlink -f -- "$INSTALL_DIR/$RECOVERY_TARGET") || \
                [[ ! -d "$PREVIOUS_RELEASE_DIR" || \
                    "$PREVIOUS_RELEASE_DIR" != "$RELEASES_DIR/"* || \
                    "$PREVIOUS_RELEASE_DIR" == "$CURRENT_ACTIVE_RELEASE" ]]; then
                log "ERROR: Release recovery target is missing or outside $RELEASES_DIR: $RECOVERY_TARGET"
                exit 1
            fi
            if [[ ! -x "$PREVIOUS_RELEASE_DIR/venv/bin/gunicorn" ]]; then
                log "ERROR: Release recovery target is not runnable: $PREVIOUS_RELEASE_DIR"
                exit 1
            fi
            PREVIOUS_LINK="$RECOVERY_TARGET"
            HAD_PREVIOUS_LINK=1
            log "Recovering the previous release pointer from the active candidate."
        else
            # Older candidates may have an empty marker from before the
            # rollback target was persisted. Retain that active path rather
            # than inventing a target that could discard a usable release.
            PREVIOUS_LINK=$(readlink -- "$CURRENT_LINK")
            PREVIOUS_RELEASE_DIR="$CURRENT_ACTIVE_RELEASE"
            HAD_PREVIOUS_LINK=1
            log "WARNING: Active candidate has no saved rollback target; retaining it for rollback."
        fi
    else
        PREVIOUS_LINK=$(readlink -- "$CURRENT_LINK")
        PREVIOUS_RELEASE_DIR="$CURRENT_ACTIVE_RELEASE"
        HAD_PREVIOUS_LINK=1
    fi
fi

if (( HAD_PREVIOUS_LINK )); then
    case "$PREVIOUS_RELEASE_DIR" in
        "$RELEASES_DIR"/*)
            PREVIOUS_LINK="releases/${PREVIOUS_RELEASE_DIR#"$RELEASES_DIR"/}"
            ;;
        *)
            log "ERROR: The validated rollback release is outside $RELEASES_DIR."
            exit 1
            ;;
    esac
fi

RELEASE_RECOVERY_TARGET="$PREVIOUS_LINK"
if (( ! HAD_PREVIOUS_LINK )); then
    RELEASE_RECOVERY_TARGET="legacy"
fi
if [[ "$RELEASE_RECOVERY_TARGET" == *$'\n'* ]] || \
    ! printf '%s\n' "$RELEASE_RECOVERY_TARGET" > "$STAGED_APP_DIR/.update-in-progress" || \
    ! sync -f -- "$STAGED_APP_DIR/.update-in-progress"; then
    log "ERROR: Could not persist the previous release pointer before activation."
    exit 1
fi

TEMP_CURRENT_LINK="$INSTALL_DIR/.current-${RELEASE_DIR_NAME}-$$"
if ! ln -s "releases/$RELEASE_DIR_NAME" "$TEMP_CURRENT_LINK" \
    || ! mv -Tf -- "$TEMP_CURRENT_LINK" "$CURRENT_LINK"; then
    rm -f -- "$TEMP_CURRENT_LINK"
    if [[ -d "$NEW_RELEASE_DIR" && ! -L "$NEW_RELEASE_DIR" ]]; then
        remove_inactive_release_path "$NEW_RELEASE_DIR" "unactivated release candidate" \
            "Unactivated release candidate removed: $RELEASE_TAG." || \
            log "WARNING: Could not remove unactivated release candidate: $NEW_RELEASE_DIR"
    fi
    log "ERROR: Could not atomically activate release $RELEASE_TAG."
    exit 1
fi
RELEASE_ACTIVATED=1

active_app_dir() {
    if [[ -L "$CURRENT_LINK" ]]; then
        printf '%s\n' "$CURRENT_LINK"
    else
        printf '%s\n' "$INSTALL_DIR"
    fi
}

wait_for_service_health() {
    local attempt active_checks=0 app_dir
    for attempt in {1..20}; do
        app_dir=$(active_app_dir)
        if sudo systemctl is-active "$SERVICE_NAME" > /dev/null && \
            "$app_dir/venv/bin/python" - "$WEB_UI_HEALTH_HOST" "$WEB_UI_PORT" <<'PY'
import json
import sys
from urllib.request import urlopen

try:
    host = sys.argv[1]
    if ":" in host:
        host = f"[{host.replace('%', '%25')}]"
    with urlopen(f"http://{host}:{sys.argv[2]}/api/status", timeout=3) as response:
        payload = json.load(response)
    if payload.get("status") != "ok":
        raise SystemExit(1)
except Exception:
    raise SystemExit(1)
PY
        then
            active_checks=$((active_checks + 1))
            if (( active_checks >= 2 )); then
                return 0
            fi
        else
            active_checks=0
        fi
        sleep 1
    done
    return 1
}

restore_previous_release() {
    local restored_pointer_durable=1
    log "Restoring the previous release pointer..."
    if (( HAD_PREVIOUS_LINK )); then
        local restore_link="$INSTALL_DIR/.current-restore-$$"
        if ! ln -s -- "$PREVIOUS_LINK" "$restore_link" \
            || ! mv -Tf -- "$restore_link" "$CURRENT_LINK"; then
            rm -f -- "$restore_link"
            log "ERROR: Could not restore the previous current release link."
            return 1
        fi
    elif [[ -L "$CURRENT_LINK" ]]; then
        if ! rm -- "$CURRENT_LINK"; then
            log "ERROR: Could not return to the legacy installation."
            return 1
        fi
    fi

    if ! sync -f -- "$INSTALL_DIR"; then
        log "ERROR: Could not persist the restored current release pointer; restored pointer durability could not be confirmed."
        restored_pointer_durable=0
        PRESERVE_RELEASE_CANDIDATE=1
    fi

    if ! sudo systemctl restart "$SERVICE_NAME"; then
        log "ERROR: The previous version could not be restarted."
        return 1
    fi
    if wait_for_service_health; then
        if (( ! restored_pointer_durable )); then
            log "ERROR: Restored pointer durability could not be confirmed; retaining rejected release candidate for startup recovery."
            log "Previous release restored and health check passed."
            return 1
        fi
        if [[ -d "$NEW_RELEASE_DIR" && ! -L "$NEW_RELEASE_DIR" ]]; then
            if rm -rf -- "$NEW_RELEASE_DIR"; then
                log "Rejected release candidate removed: $RELEASE_TAG."
            else
                log "WARNING: Could not remove rejected release candidate: $NEW_RELEASE_DIR"
            fi
        elif [[ -e "$NEW_RELEASE_DIR" || -L "$NEW_RELEASE_DIR" ]]; then
            log "WARNING: Refusing to remove unexpected rejected release path: $NEW_RELEASE_DIR"
        fi
        log "Previous release restored and health check passed."
        return 0
    fi
    log "ERROR: Previous release is selected, but its service health check failed."
    return 1
}

prune_obsolete_releases() {
    local active_release release resolved_release
    if ! active_release=$(readlink -f -- "$CURRENT_LINK"); then
        log "WARNING: Could not resolve the active release; skipping release cleanup."
        return 0
    fi

    for release in "$RELEASES_DIR"/*; do
        [[ -d "$release" && ! -L "$release" ]] || continue
        [[ -f "$release/version.json" && ! -L "$release/version.json" ]] || continue
        if ! resolved_release=$(readlink -f -- "$release"); then
            log "WARNING: Could not resolve release path; keeping it: $release"
            continue
        fi
        if [[ "$resolved_release" == "$active_release" ]]; then
            continue
        fi
        if [[ -n "$PREVIOUS_RELEASE_DIR" && "$resolved_release" == "$PREVIOUS_RELEASE_DIR" ]]; then
            continue
        fi

        if rm -rf -- "$release"; then
            log "Removed obsolete release environment: $(basename -- "$release")."
        else
            log "WARNING: Could not remove obsolete release environment: $release"
        fi
    done
}

log "Restarting $SERVICE_NAME on release $RELEASE_TAG..."
if ! sudo systemctl restart "$SERVICE_NAME"; then
    log "ERROR: Failed to restart the updated service."
    restore_previous_release || log "ERROR: Automatic recovery failed. Check: sudo systemctl status $SERVICE_NAME"
    exit 1
fi

if ! wait_for_service_health; then
    log "ERROR: The updated service did not pass its health check."
    restore_previous_release || log "ERROR: Automatic recovery failed. Check: sudo systemctl status $SERVICE_NAME"
    exit 1
fi

if ! rm -f -- "$NEW_RELEASE_DIR/.update-in-progress"; then
    log "ERROR: Could not clear the active release candidate marker: $NEW_RELEASE_DIR"
    restore_previous_release || log "ERROR: Automatic recovery failed. Check: sudo systemctl status $SERVICE_NAME"
    exit 1
fi
# Persist the marker unlink's directory metadata before reporting success.
if ! sync -f -- "$NEW_RELEASE_DIR"; then
    log "ERROR: Could not persist release marker removal for $NEW_RELEASE_DIR."
    restore_previous_release || log "ERROR: Automatic recovery failed. Check: sudo systemctl status $SERVICE_NAME"
    exit 1
fi
if ! cleanup_abandoned_release_paths; then
    log "WARNING: Could not remove every abandoned release candidate."
fi

log "Service health check passed for $RELEASE_TAG."
prune_obsolete_releases
log "========================================="
if [[ -n "${UPDATE_REQUEST_ID:-}" ]]; then
    log "Update completed successfully! (request_id=$UPDATE_REQUEST_ID)"
else
    log "Update completed successfully!"
fi
log "Active release: $RELEASE_TAG ($RELEASE_COMMIT_HASH)"
log "Backup saved to: $BACKUP_PATH"
log "========================================="

exit 0
