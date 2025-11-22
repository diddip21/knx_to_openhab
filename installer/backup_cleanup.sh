#!/usr/bin/env bash
set -euo pipefail

# Backup cleanup script for knx_to_openhab
# Reads retention settings from web_ui/backend/config.json

CONF="/opt/knx_to_openhab/web_ui/backend/config.json"
if [ ! -f "$CONF" ]; then
  echo "Config not found at $CONF, using defaults"
  BACKUPS_DIR="/var/backups/knx_to_openhab"
  DAYS=14
  MAX_BACKUPS=50
  MAX_SIZE_MB=500
else
  BACKUPS_DIR=$(python3 - <<PY
import json
cfg=json.load(open('$CONF'))
print(cfg.get('backups_dir','/var/backups/knx_to_openhab'))
PY
)
  DAYS=$(python3 - <<PY
import json
cfg=json.load(open('$CONF'))
print(cfg.get('retention',{}).get('days',14))
PY
)
  MAX_BACKUPS=$(python3 - <<PY
import json
cfg=json.load(open('$CONF'))
print(cfg.get('retention',{}).get('max_backups',50))
PY
)
  MAX_SIZE_MB=$(python3 - <<PY
import json
cfg=json.load(open('$CONF'))
print(cfg.get('retention',{}).get('max_backups_size_mb',500))
PY
)
fi

echo "Backups dir: $BACKUPS_DIR"
echo "Retention days: $DAYS, max backups: $MAX_BACKUPS, max size MB: $MAX_SIZE_MB"

if [ ! -d "$BACKUPS_DIR" ]; then
  echo "Backups dir does not exist: $BACKUPS_DIR"
  exit 0
fi

# delete by age
find "$BACKUPS_DIR" -maxdepth 1 -name '*.tar.gz' -mtime +$DAYS -print -delete || true

# enforce max backups by removing oldest
cd "$BACKUPS_DIR"
ls -1t *.tar.gz 2>/dev/null | tail -n +$((MAX_BACKUPS+1)) | xargs -r rm -f || true

# enforce size limit
TOTAL=$(du -sb . | awk '{print $1}')
MAX_BYTES=$((MAX_SIZE_MB * 1024 * 1024))
if [ "$TOTAL" -gt "$MAX_BYTES" ]; then
  echo "Total backup size $TOTAL > $MAX_BYTES, trimming oldest"
  for f in $(ls -1tr *.tar.gz 2>/dev/null); do
    if [ "$TOTAL" -le "$MAX_BYTES" ]; then break; fi
    sz=$(stat -c%s "$f")
    rm -f "$f"
    TOTAL=$((TOTAL - sz))
  done
fi

echo "Cleanup finished"
