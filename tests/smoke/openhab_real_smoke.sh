#!/usr/bin/env bash
# Real openHAB 5.2 acceptance smoke for a disposable Debian 13 QEMU VM.
# Do not execute this script on a workstation or production system.
set -Eeuo pipefail

fail() { printf 'openHAB smoke failure: %s\n' "$*" >&2; exit 1; }
note() { printf '\n==> %s\n' "$*"; }

[[ "${GITHUB_ACTIONS:-}" == true && "${CI:-}" == true ]] ||
    fail "Requires a disposable GitHub Actions test VM."
[[ "$EUID" -eq 0 ]] || fail "Must run as root inside the disposable VM."
[[ "$(cat /proc/1/comm)" == systemd ]] ||
    fail "PID 1 must be a real systemd instance."
grep -Eq '^ID=debian$' /etc/os-release || fail "This test requires Debian."
. /etc/os-release
[[ "${VERSION_ID:-}" == 13 ]] ||
    fail "Java 21 smoke currently targets Debian 13 only."

ROOT="$(pwd -P)"
APP="/opt/knx_to_openhab"
REPORT="$ROOT/test-results/openhab-real"
GENERATED="$REPORT/generated"
mkdir -p "$GENERATED"
export DEBIAN_FRONTEND=noninteractive
export APT_LISTCHANGES_FRONTEND=none

on_exit() {
    code=$?
    if (( code != 0 )); then
        printf 'FAILED openHAB smoke: %s\n' "$code" >&2
        systemctl --no-pager --full status openhab.service \
            > "$REPORT/openhab-status.txt" 2>&1 || true
        journalctl --no-pager -u openhab.service -n 220 \
            > "$REPORT/openhab-journal.txt" 2>&1 || true
        [[ ! -f /var/log/openhab/openhab.log ]] ||
            tail -n 200 /var/log/openhab/openhab.log \
                > "$REPORT/openhab-last-200.log" 2>&1 || true
        tail -n 70 "$REPORT/openhab-status.txt" >&2 || true
        tail -n 100 "$REPORT/openhab-last-200.log" >&2 || true
    fi
}
trap on_exit EXIT

note "Exercise existing real Debian installer lifecycle before adding openHAB"
bash "$ROOT/tests/smoke/debian_smoke.sh"

note "Install Java 21 and official openHAB 5.2 Debian packages"
java -version 2> "$REPORT/java-version.txt"
grep -q 'version "21' "$REPORT/java-version.txt" ||
    fail "OpenJDK 21 is not active."
curl --fail --silent --show-error --location \
    --retry 3 "https://openhab.jfrog.io/artifactory/api/gpg/key/public" |
    gpg --dearmor --yes -o /usr/share/keyrings/openhab.gpg
chmod 0644 /usr/share/keyrings/openhab.gpg
printf '%s\n' \
    'deb [signed-by=/usr/share/keyrings/openhab.gpg] https://openhab.jfrog.io/artifactory/openhab-linuxpkg stable main' \
    > /etc/apt/sources.list.d/openhab.list
apt-get update -qq > "$REPORT/openhab-apt-update.txt" 2>&1 ||
    { tail -n 60 "$REPORT/openhab-apt-update.txt" >&2; fail "openHAB APT repository unavailable."; }

apt-cache madison openhab > "$REPORT/openhab-package-versions.txt"
OH_VERSION="$(
    awk '{print $3}' "$REPORT/openhab-package-versions.txt" |
        grep -E '^5\.2\.[0-9]+([.-][0-9A-Za-z.+~-]+)?$' |
        sort -V | tail -n 1
)" || true
[[ -n "$OH_VERSION" ]] || fail "No stable openHAB 5.2 APT package is available."
if ! apt-cache madison openhab-addons | awk '{print $3}' | grep -Fxq -- "$OH_VERSION"; then
    fail "No matching openhab-addons package for $OH_VERSION."
fi
printf '%s\n' "$OH_VERSION" > "$REPORT/installed-openhab-package.txt"
if ! apt-get install -y --no-install-recommends \
    "openhab=$OH_VERSION" "openhab-addons=$OH_VERSION" \
    > "$REPORT/openhab-apt-install.txt" 2>&1; then
    tail -n 90 "$REPORT/openhab-apt-install.txt" >&2
    fail "Could not install openHAB and the matching KNX binding bundle."
fi
apt-mark hold openhab openhab-addons >/dev/null
dpkg-query -W -f='${Version}\n' openhab |
    grep -Fxq "$OH_VERSION" || fail "Installed openHAB version differs from selected 5.2 version."
test -d /etc/openhab || fail "openHAB configuration directory is missing."
id openhab >/dev/null || fail "openHAB service user was not installed."

note "Configure the real KNX binding (without contacting a physical gateway)"
mkdir -p /etc/openhab/services
printf '%s\n' 'binding = knx' > /etc/openhab/services/addons.cfg
chown openhab:openhab /etc/openhab/services/addons.cfg
chmod 0644 /etc/openhab/services/addons.cfg
# This setting and the synthetic CI admin account exist only inside the
# throwaway VM. Production openHAB security configuration is not modified.
printf '\n%s\n' 'org.openhab.restauth:allowBasicAuth=true' \
    >> /etc/openhab/services/runtime.cfg

note "Re-run the actual KNX-to-openHAB installer with /etc/openhab present"
if ! bash "$APP/installer/setup.sh" > "$REPORT/generator-with-openhab-setup.log" 2>&1; then
    tail -n 130 "$REPORT/generator-with-openhab-setup.log" >&2
    fail "Generator installer failed against real openHAB installation."
fi
systemctl is-active --quiet knxohui.service ||
    fail "knxohui.service is not active after openHAB integration setup."

note "Start openHAB systemd service"
systemctl enable --now openhab.service
systemctl is-enabled --quiet openhab.service ||
    fail "openHAB service is not enabled."
systemctl is-active --quiet openhab.service ||
    fail "openHAB service is not running."
# First start can download Karaf components and initialize the KNX binding.
READY=0
for _ in $(seq 1 150); do
    if curl --fail --silent --show-error --max-time 5 \
        -H 'Accept: application/json' \
        'http://127.0.0.1:8080/rest/items?recursive=false' \
        > "$REPORT/initial-items.json" 2>/dev/null; then
        READY=1
        break
    fi
    sleep 4
done
[[ "$READY" == 1 ]] || fail "openHAB REST API did not initialize on port 8080."
systemctl is-active --quiet openhab.service ||
    fail "openHAB died after initializing REST."
printf '%s\n' "openHAB REST API initialized." | tee "$REPORT/runtime-ready.txt"

note "Register a temporary admin through openHAB's own CSRF-protected signup"
export OPENHAB_SMOKE_USER="ci-openhab-smoke"
export OPENHAB_SMOKE_PASSWORD="ci-only-password-not-for-real-systems"
ensure_openhab_admin() {
    local phase="$1"
    if ! python3 "$ROOT/tests/smoke/create_openhab_admin.py" \
        "$OPENHAB_SMOKE_USER" "$OPENHAB_SMOKE_PASSWORD" \
        > "$REPORT/openhab-admin-${phase}.log" 2>&1; then
        tail -n 35 "$REPORT/openhab-admin-${phase}.log" >&2 || true
        fail "The disposable openHAB admin was not ready after ${phase}."
    fi
}
ensure_openhab_admin "first-start"
echo "Authenticated REST access to Items, Things and links is ready."

note "Generate live test configuration from the synthetic ETS Mini project"
PYTHONPATH="$ROOT" "$APP/venv/bin/python" \
    "$ROOT/tests/smoke/generate_openhab_fixture.py" "$GENERATED" \
    > "$REPORT/generator-output.log" 2>&1 ||
    { tail -n 100 "$REPORT/generator-output.log" >&2; fail "Generator fixture failed."; }
cat "$REPORT/generator-output.log"

note "Deploy native YAML generated by the repository and validate through REST"
install -d -o root -g openhab -m 0755 /etc/openhab/yaml
install -o knxohui -g openhab -m 0640 \
    "$GENERATED/knx.yaml" /etc/openhab/yaml/knx.yaml
systemctl restart openhab.service
ensure_openhab_admin "yaml-restart"
python3 "$ROOT/tests/smoke/verify_openhab_rest.py" \
    "$GENERATED/manifest.json" yaml "$REPORT/yaml-rest.json" ||
    fail "openHAB rejected or did not fully load the generated native YAML."

note "Switch to generated legacy Things/Items and verify native runtime loads them"
systemctl stop openhab.service
: > /etc/openhab/yaml/knx.yaml
install -d -o root -g openhab -m 0755 /etc/openhab/items
install -d -o root -g openhab -m 0755 /etc/openhab/things
install -d -o root -g openhab -m 0755 /etc/openhab/sitemaps
install -o knxohui -g openhab -m 0640 "$GENERATED/knx.items" /etc/openhab/items/knx.items
install -o knxohui -g openhab -m 0640 "$GENERATED/knx.things" /etc/openhab/things/knx.things
install -o knxohui -g openhab -m 0640 \
    "$GENERATED/knx.sitemap" /etc/openhab/sitemaps/knx.sitemap
systemctl start openhab.service
ensure_openhab_admin "legacy-start"
python3 "$ROOT/tests/smoke/verify_openhab_rest.py" \
    "$GENERATED/manifest.json" legacy "$REPORT/legacy-rest.json" ||
    fail "openHAB rejected or did not fully load the generated legacy Things/Items."

note "Ensure real services survived openHAB loading and a restart"
systemctl restart openhab.service
systemctl is-active --quiet knxohui.service
systemctl is-active --quiet openhab.service
ensure_openhab_admin "legacy-restart"
python3 "$ROOT/tests/smoke/verify_openhab_rest.py" \
    "$GENERATED/manifest.json" legacy-after-restart "$REPORT/legacy-restart-rest.json"

note "Exercise the REAL Web UI upload, generator, deploy, repeat and rollback"
# Unlike the direct-file smoke checks above, this drives authenticated
# /api/upload -> /api/job/<id> -> /api/job/<id>/deploy -> /rollback, verifies
# actual managed file writes and checks only NEW openHAB parser/ERROR logs.
if ! python3 "$ROOT/tests/smoke/web_deploy_e2e.py" \
    "$ROOT/tests/fixtures/mini_project.json" "$REPORT" \
    > "$REPORT/web-deploy.log" 2>&1; then
    tail -n 140 "$REPORT/web-deploy.log" >&2
    fail "Real Web UI upload/deploy/rollback or openHAB log validation failed."
fi
cat "$REPORT/web-deploy.log"

printf '%s\n' \
    "PASS: openHAB $OH_VERSION + real Web upload, generation, repeated deploy, YAML transition, REST verification, log guard and rollback" \
    | tee "$REPORT/summary.txt"
