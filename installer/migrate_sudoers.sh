#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
POLICY_SOURCE="$SCRIPT_DIR/knxohui.sudoers"
SUDOERS_FILE="/etc/sudoers.d/knxohui"

if [[ "$EUID" -ne 0 ]]; then
    echo "Run this migration as an administrator: sudo bash $SCRIPT_DIR/migrate_sudoers.sh" >&2
    exit 1
fi

TEMP_POLICY="$(mktemp /etc/sudoers.d/.knxohui.XXXXXX)"
BACKUP_POLICY=""
cleanup() {
    rm -f "$TEMP_POLICY"
    if [[ -n "$BACKUP_POLICY" ]]; then
        rm -f "$BACKUP_POLICY"
    fi
}
trap cleanup EXIT

install -o root -g root -m 0440 "$POLICY_SOURCE" "$TEMP_POLICY"
visudo -cf "$TEMP_POLICY"

if [[ -e "$SUDOERS_FILE" ]]; then
    BACKUP_POLICY="$(mktemp /root/knxohui-sudoers.XXXXXX)"
    cp -p "$SUDOERS_FILE" "$BACKUP_POLICY"
fi

mv -f "$TEMP_POLICY" "$SUDOERS_FILE"
if ! visudo -c; then
    if [[ -n "$BACKUP_POLICY" ]]; then
        cp -p "$BACKUP_POLICY" "$SUDOERS_FILE"
    else
        rm -f "$SUDOERS_FILE"
    fi
    echo "Combined sudoers validation failed; the previous policy was restored." >&2
    exit 1
fi

echo "Restricted KNX to openHAB sudoers policy installed and validated."
