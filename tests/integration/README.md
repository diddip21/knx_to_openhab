# Transactional updater integration and acceptance

Run the assembled lifecycle with the project's Python 3.12 environment:

```sh
ulimit -Sn 32768
python -m pytest -q tests/integration/test_update_transaction.py -o addopts=
```

Linux root is needed **only** for disposable `/run/knxoh-assembled-*` ownership,
protected filesystem operations and demoting children. Candidate migration,
dependency installation (empty requirements, local venv only), extraction and app
startup run with non-root numeric fixture identities, with no account creation.
Root must not execute candidate preparation/migration or application servers.
Trusted test fixtures use backend serialization helpers to seed/inspect shared data;
the production privileged coordinator still imports no application modules.
No host service, policy, account,
installed file, global Python environment or resource-limit configuration is changed.
The fixture's local loopback server supplies metadata/archive/checksum bytes through
a test-only downloader; genuine GitHub URL and coordinator metadata/checksum/tree
validation remain in place. It does not download public releases or pip packages.
The app processes use the existing test interpreter/dependencies to execute each
selected release's actual backend source, not the prepared empty-requirements
candidate venv. Candidate venv creation and its Python/pip invocation are real,
but installation of the production dependency set and launcher interpreter choice
belong to the still-missing disposable installed-unit acceptance.

## What the ordinary suite proves (and does not)

- Actual coordinator, journal, protected snapshots/gate, exclusive lifecycle lock,
  real preparation stages, SHA verification, archive extraction, final-path venv,
  copied-config CLI under `python3 -I`, freeze and atomic publication.
- Default stable and explicit prerelease; already current; corrupt archive;
  failed copied migration and candidate HTTP readiness; rollback serves old Flask
  app; custom paths with spaces; clean same-version dependency retry.
- Real unprivileged submit client publishes its request and waits for the real
  protected matching-ID coordinator claim; facade reads the real committed projection.
- Old and candidate fixture releases contain the actual current backend sources
  (different `VERSION` files), not independently published historical versions.
  Both start against a real SQLite session DB and JSON job index. The candidate
  reads old records and writes sessions/jobs; failed readiness then starts old
  source again, which must read those candidate-written records. This is a
  protocol-1 regression obligation for future source changes, **not** proof for
  arbitrary older published releases or a manifest compatibility flag alone.
- Process exit without cleanup after actual config/link replacement; startup deny
  for UI/cleanup, fixed boot-mode recovery and corrupt-journal refusal. These are
  real filesystem/process interruptions, **not an actual machine reboot**.
- Config bytes/metadata and unrelated config/secrets/runtime/backup sentinels survive.

Service starts/stops, notify state, and child-cgroup teardown evidence are **fake
manager effects**. Local process-group cleanup is not cgroup isolation. The real
Flask HTTP listener is not the installed launcher/notify lifecycle (the separate
`tests/test_update_http_serving.py` runs actual deployed Gunicorn configuration).
The queued-Future cancellation obligation is in `tests/test_update_maintenance.py`.

## Opt-in REAL systemd acceptance: disposable guest only

**NOT VERIFIED in the development environment.** WSL PID 1 systemd is not permission
to mutate its host manager. No Docker/Podman/nspawn/QEMU disposable provider is
available here. `unshare` alone is not a provisioned disposable systemd guest and
must not be used to bypass these prerequisites. Do not install providers globally,
create host users, install units/policy, or alter host services to run this suite.

An administrator/CI owner must separately supply a throwaway Linux VM/container
with systemd as PID 1, working cgroup/namespace isolation, distro `sudo`, Python
venv support, project test dependencies, and a verified installed updater bundle,
units, worker/UI identities, sudo policy, custom canonical paths **containing spaces**,
and a runnable notify-ready application. Provision only inside the guest, not via
this test. The tests execute actual unit starts/stops and a hostile migration
candidate, so **destroy the complete guest afterward**. Never reuse production data.

The image must contain root-owned mode-0600
`/etc/knxoh-disposable-systemd-test.json`:

```json
{"disposable":true,"machine_id":"GUEST_ETC_MACHINE_ID","nonce":"INDEPENDENT_RANDOM_NONCE"}
```

Provide a root-owned non-writable configuration file, e.g. `/root/acceptance.json`:

```json
{
  "nonce":"INDEPENDENT_RANDOM_NONCE",
  "paths_file":"/etc/knx_to_openhab/paths.env",
  "prior_boot_id":"BOOT_ID_CAPTURED_BEFORE_THE_TEST_BOOT",
  "offline_lock_absent":true
}
```

Before that test boot, the guest owner must verify **offline** in the disposable
image that `/run/lock/knxohui-lifecycle.lock` is absent, retain the provisioning/boot
transcript, and record the old boot ID. This is external evidence/attestation, not
something the pytest flag can prove retrospectively. Never unlink a live host lock.
Boot the guest normally and retain its boot journal; do not replace ExecStart with
`true` or mock systemctl. Wait for the cleanup timer's first real service invocation
before running the suite: it asserts a real cleanup ExecMainStart timestamp as
well as UI/timer activation, not an unstarted oneshot's zero ActiveEnter timestamp.
Inside that guest only:

```sh
export KNXOH_DISPOSABLE_SYSTEMD=destroy-this-guest
export KNXOH_DISPOSABLE_SYSTEMD_NONCE=INDEPENDENT_RANDOM_NONCE
export KNXOH_DISPOSABLE_SYSTEMD_CONFIG=/root/acceptance.json
python -m pytest -q tests/integration/test_update_systemd.py -o addopts=
journalctl -b --no-pager > /root/acceptance-boot-journal.txt
```

Guards require the explicit marker, nonce, machine ID, fresh boot ID, root-only
configuration, virtualization detection, and reject WSL/nonvirtual hosts before
any service operation. Markers do not create an isolation boundary; the guest
provider and offline transcript are mandatory independent prerequisites.

The suite checks real tmpfiles/recovery/writer activation timestamps and dependencies,
notify state and no reported ordering cycle; runs the installed preparation worker
through the production `SystemdAdapter` sandbox with a malicious migration that
tries to read live config, secrets, runtime, backup and recovery state, tries sudo,
and leaves a SIGTERM-ignoring descendant writer; then requires real cgroup teardown
and no subsequent writes. It also corrupts only the disposable journal and verifies
actual failed recovery blocks UI **and** cleanup service/timer before restoring
the fixture. Evidence is intentionally retained in the guest until review/destruction.

This harness has **not itself received a real-manager run** here. Resource-exhaustion,
real boot interrupted at each mutation phase, and the complete production-unit
update/rollback/installer race must still be exercised in that guest before full
feature acceptance. Do not equate default skips, static unit verification, mocked
manager tests or local HTTP success with those missing real acceptance results.

## Repository verification

The current pytest configuration includes UI tests: exclude them explicitly for core:

```sh
python -m pytest -q --ignore=tests/ui
python -m pytest -q tests/ui/test_update_system.py -o addopts= --browser chromium
python -m black --check .
python -m isort --check-only .
python -m flake8 .
git diff --check
```

Run core both as root (ownership fixtures) and as a non-root identity (non-root
installer/uninstall fixtures); report platform skips. The browser fixture launches
the actual local Flask app and actual JavaScript, but injects lifecycle API responses:
it must not submit a host update. Existing checking/committed screenshots remain
valid when no UI appearance changes. No CI workflow change belongs to this task.

For root core verification, supply a fresh **root-private** pytest base under
protected ancestry, not the default world-writable `/tmp` (secure administrator
snapshot tests deliberately reject that ancestry):

```sh
python -m pytest -q --ignore=tests/ui --basetemp="$(mktemp -d /run/knxoh-pytest-XXXXXX)"
```

If the checkout has a Windows Git worktree pointer unusable from WSL, use native
Git to archive HEAD with `-c core.autocrlf=false`, overlay the changed source files
with recorded SHA-256 hashes, and verify LF shell bytes in an isolated Linux
snapshot before running. Keep local venvs/ignored handoff files outside that snapshot
so repository-wide isort/flake8 checks do not scan third-party packages. Do not
reset the real worktree or change Git metadata to make the test environment work.
