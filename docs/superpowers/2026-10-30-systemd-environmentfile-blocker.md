# Real systemd acceptance: custom EnvironmentFile rejected (2026-10-30)

**BLOCKED by a new production unit-rendering defect. Full acceptance is not
complete.** No production code or installed unit was edited to work around it.

## Real progress before the failure

- Current provider preflight and strict recorded-partial inventory passed.
  Controller pinned the actual checkpoint outside the guest; no unknown state was
  adopted and no old lock/source tree was removed.
- New immutable production `47e2c3a3cd59d716f793226ec17badde60999eca` (**246 files**)
  and harness `fd47f6a3ef088549d5bb1de5d9fad72d822a3e42` (**250 files**) were deployed
  separately and completely hash/owner/mode verified. Old 27d106a/d1f1848 remain.
- Real Linux sudo RED→GREEN: **1 passed**, using the actual new 47e2c3a validator,
  UID/EUID 0 and `NoNewPrivs: 0`. Actual sudo still returns exit 0 with sole complete
  denial; no result was faked and no worker grant was added. Identity/no-grant
  validation also passed again after the real sudoers installation.
- Explicit `resume-after-sudo` passed the checkpoint/source checks again under the
  retained lifecycle lease, installed the real protected bundle/policy/units, and
  built the actual initial final-path venv from all original requirements and
  approved offline wheels (`--no-index --only-binary=:all:`). No empty requirements,
  fake interpreter, package build hook or worker-created root venv was used.
- Independent initial-release scan found **3354** root-owned, non-service-writable,
  link-free entries. Actual initial-venv `pip check` reports no broken requirements.
  Gunicorn has the real final-path launcher, not the test interpreter.
- The actual recovery unit completed successfully (`active/exited`, status 0,
  journal result `clean`) with the configured custom paths and sandbox properties.
  This is a same-boot execution/opening smoke, **not** separately captured mount-ID
  isolation proof, a machine reboot or complete confinement acceptance.

## Observed production failure

Real systemd **255 (255.4-1ubuntu8)** rejects the production-rendered writer drop-in:

```ini
[Service]
EnvironmentFile=
EnvironmentFile="/etc/knxoh acceptance config/paths.env"
```

The real journal reports:

```text
EnvironmentFile= path is not absolute, ignoring: "/etc/knxoh acceptance config/paths.env"
```

Both UI and backup-cleanup service lose the canonical environment contract. Their
real PID-1 D-Bus `EnvironmentFiles` property is `{"type":"a(sb)","data":[]}`.
UI Type=notify startup fails with status 1; cleanup fails too. No Gunicorn/HTTP
readiness success is claimed. The drop-in bytes were verified equal to the actual
47e2c3a production `render_dropins()` output, not a handwritten fixture unit.

`tests/integration/test_update_environment_runtime.py` makes **only real read-only
D-Bus/file queries** and reproduces this as **2 failed** (UI and cleanup). It checks
the protected own-path contract and exact production rendering before querying
the actual loaded unit property. It neither starts nor modifies a service.
Ordinary unconfigured collection skips both cases.

The new regression can be run inside the authorized guest after controller
preflight, with the immutable production source and reviewed harness on the
explicit test import paths:

```sh
KNXOH_LIVE_SYSTEMD_ENV_ACCEPTANCE=own-nested-read-only \
KNXOH_DISPOSABLE_SYSTEMD_NONCE="${ORIGINAL_PRIVATE_NONCE:?}" \
/opt/knxoh-test-venv/bin/python -B -m pytest -q \
  tests/integration/test_update_environment_runtime.py -k installed_writer \
  -o addopts= -p no:cacheprovider
```

The recorded run copied only this trusted regression to a private root-owned,
hash-named test directory, avoiding project conftest side effects. Exact native
commands/logs are in the ignored incremental report and companion scripts.

## Retained safe state and next checkpoint

- Own-guest UI restart loop and cleanup timer/service were explicitly stopped,
  not reset or replaced. UI is inactive/dead, with retained exit-code result and
  status 1; cleanup retains failed status 1; timer inactive. UI's recorded restart
  count was 19 before stopping. Recovery remains active/exited; updater inactive
  and **never invoked**. Units remain enabled as originally provisioned; do not
  boot/start them to bypass this defect.
- Installed bundle, units, real initial release/venv/current and private external
  credentials are retained for review. Original config/generator/paths hashes are
  unchanged; sibling settings were not overwritten. Jobs/staging/generated remain
  empty. Original lifecycle lock inode/owner/mode are unchanged and independently
  acquirable; it was never unlinked.
- The nested boot ID remains `4ef02c08-118a-4630-be3d-a348c9937c91`. No reboot,
  offline-lock attestation or power-loss proof was fabricated. Existing Ubuntu,
  Windows/global WSL settings/services/mounts and the outer application manager
  were untouched; all app effects stayed inside the authorized nested fixture.
- Raw logs/receipts/pins/credentials remain ignored or root-private in the guest.
  See `.superpowers/sdd/2026-10-28-transactional-release-updater/wsl-acceptance/wsl-acceptance-report.md`
  and `resume-47e2c3a/resume-after-sudo.log`, `activation_diagnostic_47.log`,
  `environment_live_pytest_47.log`, `installed_blocked_state_execute_47.log`.

Next: independently review a targeted production EnvironmentFile rendering fix
and an explicit guarded **installed-component repair** checkpoint, preserving
this initial environment and all external state. Do not edit the immutable source
or installed drop-ins manually, rename custom paths, inject replacement environment
variables, repeat fresh bootstrap, or repeat the now-obsolete after-sudo checkpoint.

No child isolation/cgroup/resource probe, actual boot/offline-lock suite, complete
installed update/rollback/no-update, local HTTPS release fixture, authenticated
API/notify/health acceptance or final core suite has run. Parent Task 5 remains
incomplete; user-space nspawn/WSL evidence is not physical power-loss evidence.

Delivery checks: the actual Linux installed-writer selection reports **2 failed,
4 deselected** after final formatting. Native decoder checks report **4 passed,
2 live cases skipped**. Black/isort/flake8 pass for the new regression; full
native/core/UI suites were not run. This failure concerns EnvironmentFile parsing;
do not blindly change quoting used by other unit fields, whose parsing differs.

## Targeted rendering candidate (not installed)

`render_dropins()` now emits the validated path directly for `EnvironmentFile=`
only. In systemd v255 `src/core/load-fragment.c`,
`config_parse_unit_env_file()` passes the **whole** right-hand side through
specifier expansion and absolute-path checking without word extraction or
unquoting. Thus spaces belong to the path, while surrounding quotes are literal
and invalidate the absolute path. `ExecStart=` and `ReadWritePaths=` retain their
separate quoted-word grammars. Existing path validation, canonical configuration,
required-file behavior and the list reset remain unchanged; no environment
overrides, keys or dependencies were added.

Portable regression: both writers with default and custom-space contract paths
failed before the fix (**4 failed, 9 passed**) and pass afterward. The existing
custom-space static test now also rejects `EnvironmentFile=` parser diagnostics:
real Ubuntu systemd 255 reproduced **1 failed** before the fix despite `verify`
returning 0, then **1 passed** afterward. This is static parsing, not installed
writer runtime acceptance.

`test_disposable_pid1_parses_production_environment_file` adds a separately
opt-in real-PID-1 parser check for the authenticated own nested fixture. It
exclusively creates a UUID-named `/run/systemd/system/knxoh-env-parser-*.service`,
uses `LoadUnit` and the real D-Bus `EnvironmentFiles` property, and removes only
that fixture file. It neither starts services nor reloads/edits app units. This
new live check has **not** been run; default collection skips it.

Controller must independently review this production change **and** the separate
guarded installed-component repair runner before guest effects. After explicit
repair, rerun the original `-k installed_writer` command above and require the
recorded **2 failed → 2 passed** result on actual installed production-rendered
drop-ins. The stopped-writer checkpoint and all remaining acceptance limits above
remain in force; do not hand-edit drop-ins or claim runtime success from static
validation.
