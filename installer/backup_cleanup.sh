#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PYTHON="$APP_DIR/venv/bin/python"
if [[ ! -x "$PYTHON" ]]; then
    PYTHON="$APP_DIR/.venv/bin/python"
fi
if [[ ! -x "$PYTHON" ]]; then
    PYTHON=python3
fi

readarray -t SETTINGS < <(PYTHONPATH="$APP_DIR" "$PYTHON" - "$APP_DIR" <<'PY'
import json
import sys
sys.path.insert(0, sys.argv[1])
from web_ui.backend.storage import load_config
config = load_config(sys.argv[1])
print(config["backups_dir"])
retention = config.get("retention", {})
print(int(retention.get("days", 14)))
print(int(retention.get("max_backups", 50)))
print(int(retention.get("max_backups_size_mb", 500)))
PY
)

if [[ "${#SETTINGS[@]}" -ne 4 ]]; then
    echo "Unable to load the backup retention settings" >&2
    exit 1
fi
BACKUPS_DIR="${SETTINGS[0]}"
DAYS="${SETTINGS[1]}"
MAX_BACKUPS="${SETTINGS[2]}"
MAX_SIZE_MB="${SETTINGS[3]}"

echo "Backups dir: $BACKUPS_DIR"
echo "Retention days: $DAYS, max backups: $MAX_BACKUPS, max size MB: $MAX_SIZE_MB"
if [[ ! -d "$BACKUPS_DIR" ]]; then
    echo "Backups dir does not exist: $BACKUPS_DIR"
    exit 0
fi

find "$BACKUPS_DIR" -maxdepth 1 -type f -name '*.tar.gz' -mtime "+$DAYS" -print -delete
mapfile -t BACKUPS < <(find "$BACKUPS_DIR" -maxdepth 1 -type f -name '*.tar.gz' -printf '%T@ %p\n' | sort -rn | cut -d' ' -f2-)
for ((index = MAX_BACKUPS; index < ${#BACKUPS[@]}; index++)); do
    rm -f -- "${BACKUPS[$index]}"
done

mapfile -t BACKUPS < <(find "$BACKUPS_DIR" -maxdepth 1 -type f -name '*.tar.gz' -printf '%T@ %s %p\n' | sort -n)
TOTAL=0
for record in "${BACKUPS[@]}"; do
    size="${record#* }"
    size="${size%% *}"
    TOTAL=$((TOTAL + size))
done
MAX_BYTES=$((MAX_SIZE_MB * 1024 * 1024))
for record in "${BACKUPS[@]}"; do
    if ((TOTAL <= MAX_BYTES)); then
        break
    fi
    size="${record#* }"
    size="${size%% *}"
    file="${record#* * }"
    rm -f -- "$file"
    TOTAL=$((TOTAL - size))
done

echo "Cleanup finished"
