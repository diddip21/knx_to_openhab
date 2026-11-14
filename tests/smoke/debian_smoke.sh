#!/usr/bin/env bash
# Execute ONLY inside a disposable GitHub Actions Debian VM.
# This exercises the actual installer against real systemd, users and files.
set -Eeuo pipefail

fail() {
    printf 'SMOKE FAILED: %s\n' "$*" >&2
    exit 1
}

log() {
    printf '\n==> %s\n' "$*"
}

[[ "$CI" == "true" && "$GITHUB_ACTIONS" == "true" ]] ||
    fail "GitHub Actions is required; do not run this on a real host."
[[ "$(id -u)" == "0" ]] || fail "The disposable VM test requires root."
[[ "$(cat /proc/1/comm)" == "systemd" ]] ||
    fail "PID 1 is not systemd; this would not test the real service lifecycle."
grep -Eq '^ID=debian$' /etc/os-release || fail "This test requires real Debian."

SRC="$(pwd -P)"
BASE="/opt/knx_to_openhab"
CONFIG="/etc/knx_to_openhab"
DATA="/var/lib/knx_to_openhab"
BACKUPS="/var/backups/knx_to_openhab"
REPORT="$SRC/test-results/debian-smoke"
FAKE_PASSWORD="smoke-only-not-a-secret-12345"
PORT_LISTENER_PID=""

mkdir -p "$REPORT"

on_exit() {
    status=$?
    if [[ -n "$PORT_LISTENER_PID" ]]; then
        kill "$PORT_LISTENER_PID" >/dev/null 2>&1 || true
        wait "$PORT_LISTENER_PID" >/dev/null 2>&1 || true
    fi
    if (( status != 0 )); then
        echo "Debian smoke failed (exit status $status)" >&2
        systemctl --no-pager --full status knxohui.service > "$REPORT/systemctl-status.log" 2>&1 || true
        journalctl --no-pager -u knxohui.service -n 160 > "$REPORT/journal.log" 2>&1 || true
        tail -n 75 "$REPORT/systemctl-status.log" >&2 || true
        tail -n 75 "$REPORT/journal.log" >&2 || true
    fi
}
trap on_exit EXIT

log "Debian VM and systemd details"
cat /etc/os-release | tee "$REPORT/debian-release.txt"
systemctl --version | head -n 1
python3 --version
test ! -e "$BASE" || fail "Refusing to reuse an existing installation directory."
test ! -e /etc/systemd/system/knxohui.service ||
    fail "Refusing to replace a pre-existing knxohui systemd unit."

log "Populate the real installation with synthetic legacy configuration and jobs"
mkdir -p "$BASE"
rsync -a --exclude .git --exclude .venv --exclude test-results/ "$SRC/" "$BASE/"
python3 - "$BASE" <<'PY'
import json
import sys
from pathlib import Path

base = Path(sys.argv[1])
generator = base / "config.json"
original = json.loads(generator.read_text(encoding="utf-8"))
original["ci_smoke_marker"] = "must-survive-repair"
generator.write_text(json.dumps(original, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

legacy = base / "web_ui/backend/config.json"
config = json.loads(legacy.read_text(encoding="utf-8"))
config.update({"bind_host": "127.0.0.1", "port": 8085})
config["auth"] = {
    "enabled": True,
    "mode": "basic",
    "user": "smoke",
    "password": "smoke-only-not-a-secret-12345",
}
legacy.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

jobs = base / "var/lib/knx_to_openhab"
backups = base / "var/backups/knx_to_openhab"
jobs.mkdir(parents=True)
backups.mkdir(parents=True)
upload = jobs / "smoke-upload.knxproj"
upload.write_text("synthetic upload - not a real ETS project\n", encoding="utf-8")
backup = backups / "smoke-backup.tar.gz"
backup.write_bytes(b"synthetic backup payload")
(jobs / "jobs.json").write_text(
    json.dumps({
        "smoke-job": {
            "id": "smoke-job",
            "input": str(upload),
            "backups": [{"path": str(backup), "name": backup.name}],
        }
    }) + "\n",
    encoding="utf-8",
)
PY

log "Check that an unrelated systemd unit is never overwritten"
cat > /etc/systemd/system/knxohui.service <<'UNIT'
[Unit]
Description=Foreign unit used only for Debian smoke test
[Service]
ExecStart=/bin/false
UNIT
systemctl daemon-reload
if bash "$BASE/installer/setup.sh" > "$REPORT/foreign-unit.log" 2>&1; then
    fail "Setup overwrote or accepted the unrelated systemd unit."
fi
grep -q "Refusing to replace an unrecognized systemd unit" "$REPORT/foreign-unit.log" ||
    fail "Foreign-unit test failed for a reason other than ownership protection."
grep -q "Foreign unit used only for Debian smoke test" /etc/systemd/system/knxohui.service ||
    fail "The unrelated unit was changed."
rm /etc/systemd/system/knxohui.service
systemctl daemon-reload

log "First real setup (real systemd, sudo, virtualenv, migration, permissions)"
if ! bash "$BASE/installer/setup.sh" > "$REPORT/first-setup.log" 2>&1; then
    tail -n 100 "$REPORT/first-setup.log" >&2
    fail "Fresh installation failed."
fi

wait_web() {
    for _ in $(seq 1 30); do
        if curl --silent --fail --max-time 3 \
            --user "smoke:$FAKE_PASSWORD" http://127.0.0.1:8085/ >/dev/null; then
            return 0
        fi
        sleep 2
    done
    fail "Web UI did not respond to authenticated requests."
}

check_runtime_data() {
    python3 - "$BASE" "$CONFIG" "$DATA" "$BACKUPS" <<'PY'
import base64
import json
import sys
from pathlib import Path

base, config_dir, data_dir, backup_dir = map(Path, sys.argv[1:])
generator = json.loads((data_dir / "generator.json").read_text(encoding="utf-8"))
assert generator["ci_smoke_marker"] == "must-survive-repair"
config = json.loads((config_dir / "config.json").read_text(encoding="utf-8"))
assert config["bind_host"] == "127.0.0.1"
assert config["port"] == 8085
assert "password" not in config.get("auth", {})
assert config["jobs_dir"] == str(data_dir / "jobs")
upload = data_dir / "jobs/smoke-upload.knxproj"
assert upload.read_text(encoding="utf-8") == "synthetic upload - not a real ETS project\n"
assert (backup_dir / "smoke-backup.tar.gz").read_bytes() == b"synthetic backup payload"
jobs = json.loads((data_dir / "jobs/jobs.json").read_text(encoding="utf-8"))
assert jobs["smoke-job"]["input"] == str(upload)
assert jobs["smoke-job"]["backups"][0]["path"] == str(backup_dir / "smoke-backup.tar.gz")
secrets = (config_dir / "secrets.env").read_text(encoding="utf-8")
hashline = next(line for line in secrets.splitlines() if line.startswith("KNXOH_UI_PASSWORD_HASH_B64="))
assert base64.b64decode(hashline.partition("=")[2]).startswith(b"$argon2id$")
assert "smoke-only-not-a-secret" not in secrets
assert not (base / "var/lib/knx_to_openhab").exists()
assert not (base / "var/backups/knx_to_openhab").exists()
PY
}

systemctl is-active --quiet knxohui.service || fail "Web UI service is not active."
systemctl is-active --quiet knxohui-backup-cleanup.timer ||
    fail "The cleanup timer is not active."
systemctl is-enabled --quiet knxohui.service || fail "Web UI service is not enabled."
wait_web
check_runtime_data
visudo -c >/dev/null

log "Second full setup through install.sh --repair (same installed PR code)"
if ! ALLOW_ROOT=1 bash "$BASE/install.sh" --repair > "$REPORT/repair.log" 2>&1; then
    tail -n 100 "$REPORT/repair.log" >&2
    fail "Repair failed on the existing installation."
fi
systemctl is-active --quiet knxohui.service || fail "Web UI did not restart after repair."
wait_web
check_runtime_data

log "Inject a failure after service quiescence and verify restoration"
FAULT_SRC="$(mktemp -d /tmp/knxoh-smoke-fault.XXXXXXXX)"
rsync -a --exclude .git --exclude .venv --exclude test-results/ "$SRC/" "$FAULT_SRC/"
printf '%s\n' 'this is intentionally not a valid pip requirement !!' >> "$FAULT_SRC/requirements.txt"
if bash "$FAULT_SRC/installer/setup.sh" > "$REPORT/recovery.log" 2>&1; then
    fail "Fault-injection setup unexpectedly succeeded."
fi
grep -q "Setup failed; restoring services that were active before migration" \
    "$REPORT/recovery.log" ||
    fail "Setup did not attempt to restore previously active services."
systemctl is-active --quiet knxohui.service ||
    fail "Web UI was not restored after a real setup failure."
wait_web
check_runtime_data
rm -rf "$FAULT_SRC"

log "Reject a real TCP port collision without losing migrated files"
systemctl stop knxohui.service
python3 -m http.server 8085 --bind 127.0.0.1 \
    > "$REPORT/port-listener.log" 2>&1 &
PORT_LISTENER_PID=$!
for _ in $(seq 1 12); do
    if curl --silent --fail --max-time 1 http://127.0.0.1:8085/ >/dev/null; then
        break
    fi
    sleep 1
done
kill -0 "$PORT_LISTENER_PID" >/dev/null 2>&1 ||
    fail "Could not start the competing TCP listener."

if bash "$BASE/installer/setup.sh" > "$REPORT/port-conflict.log" 2>&1; then
    fail "Setup did not reject a real TCP listener on the Web UI port."
fi
grep -q "The Web UI address is unavailable" "$REPORT/port-conflict.log" ||
    fail "Setup rejected the port for an unexpected reason."
check_runtime_data
kill "$PORT_LISTENER_PID" >/dev/null 2>&1
wait "$PORT_LISTENER_PID" >/dev/null 2>&1 || true
PORT_LISTENER_PID=""
systemctl start knxohui.service
wait_web

log "Real systemd restart and persistent service settings"
systemctl restart knxohui.service
systemctl is-active --quiet knxohui.service
systemctl is-enabled --quiet knxohui.service
wait_web
check_runtime_data

printf '%s\n' "PASS: first install, repair, migration, rollback, port collision, foreign unit and systemd restart" \
    | tee "$REPORT/summary.txt"
