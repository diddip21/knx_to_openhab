# Installed repair: component GREEN, runner readiness endpoint blocked

## Current outcome

The explicitly authorized `repair-environmentfile` execution installed the reviewed
production source **2dcf3078b61283a41fd1ef38e34327e4f759d5c1**, based on old
47e2c3a with exactly the three approved 49dd676 blobs. The reviewed harness was
**829992fb22430bce47eb45570d8a64d71ba817e0**, separately deployed and hash-verified.
Controller approval of the exact external inputs preceded effects; no observation
was silently enrolled as a new approved checkpoint.

- Actual installed-writer regression: previous **2 failed** -> **2 passed,
  6 deselected in 0.07s**. Executed the immutable production file
  `tests/integration/test_update_environment_runtime.py -k installed_writer`
  with `/opt/knxoh-test-venv/bin/python`, against actual production-rendered installed
  drop-ins and actual typed PID-1 `EnvironmentFiles` properties. Not a parser-only
  fixture, replacement unit, mocked manager, or production-environment injection.
- Complete initial **3354 entries**, hashes/modes/owners/device/inodes, current
  target, original config/credentials/locks and external/runtime state preserved.
  Exact repaired component bytes/renderer and retained old bundle bytes/inodes
  verified before activation and again read-only afterward.
- Actual UI `Type=notify` reached active/running with gunicorn on
  `127.0.0.1:8085`, result/status success/0, restart count 19 unchanged. This is
  notify activation evidence, **not** an application-health response/version proof.
- The repair phase exited **1** on HTTP **302 FOUND** from the runner's wrong
  `/health` endpoint. Its failure handler stopped only own UI/cleanup writers.

Private incremental report, exact commands/pins, preflights and logs remain under
`.superpowers/sdd/2026-10-28-transactional-release-updater/wsl-acceptance/`:
`repair-execution-report.md` and `repair-execution-829992f/`.
No credentials, nonce, or private credential hashes are published here.

## Minimal root cause and regression

`scripts/nested_fixture_repair.py:824` opens
`http://127.0.0.1:8085/health` with redirects deliberately disabled.
The production route is **`/api/health`** (`web_ui/backend/app.py:292–298`),
which returns readiness JSON and the actual running version. Its auth exemption
is at app.py:242; an unauthenticated non-API `/health` request instead redirects to
login (app.py:234–259). The real gunicorn access log records `GET /health ... 302`,
matching the actual urllib HTTPError. No production fix is indicated by this error.

New portable regression:

```text
python -B -m pytest -q tests/test_nested_repair_health_contract.py -o addopts= --tb=short -p no:cacheprovider
1 failed in 0.18s
assert ['http://127.0.0.1:8085/health'] == ['http://127.0.0.1:8085/api/health']
```

The regression now has an explicit **strict xfail** documenting the unfixed known
runner defect. It does not claim runtime success; network transport is a spy for
the URL contract only. Removing the mismatch requires separate reviewed runner
work. This delivery does not change any repair/production implementation or patch
the deployed immutable harness.

Final focused native harness verification: **112 passed, 1 xfailed in 27.18s**;
the xfail is this explicitly retained known endpoint defect, not GREEN. Black,
isort, flake8 over the new regression and `git diff --check` exited 0. No full
Windows/core/UI suite or final Linux acceptance suite was run.

## Retained manager state

| Unit | Active / Sub | Result / status | MainPID | Restarts |
| --- | --- | --- | --- | --- |
| UI | inactive / dead | success / 0 | 0 | 19 |
| Cleanup service | failed / failed | exit-code / 1 | 0 | 0 |
| Cleanup timer | inactive / dead | success / 0 | 0 | 0 |
| Updater | inactive / dead | success / 0 | 0 | 0 |
| Recovery | active / exited | success / 0 | 0 | 0 |

No own manager jobs. Historical cleanup failure was not reset or rerun. Updater
was not invoked. Recovery `start` during activation was a no-op on its existing
active/exited instance; its journal still records the earlier `clean` result.
Loaded updater/recovery `ReadWritePaths` anchors were captured; this is not a new
runtime namespace/cgroup proof. Same real inner boot identity remains; no reboot.
Gunicorn additionally logged a nonfatal control-server permission error for
`/nonexistent`; it nevertheless served the observed HTTP request. This incidental
warning has not been diagnosed as a production readiness defect.

## Proceed boundary

**Stop here.** The exact original pre-repair checkpoint is consumed and must not
be rerun. No automatic retry, fresh bootstrap, obsolete continuation, state cleanup,
reenrollment, environment workaround, path rename, credential change, root candidate
execution, or manager restart was attempted after the error. All old source/harness
trees and previous evidence remain retained. Only current-guarded read-only
regression/property/inventory/journal queries followed the failure.

A controller-reviewed endpoint correction and explicitly authorized next known
installed-state transition are required before restarting writers to prove actual
`/api/health` JSON/version **0.1.0**. Do not treat either notify activation or the
loaded-property GREEN as that response. The hostile probe was withheld because
the entire readiness phase did not succeed. No corrupt-journal, update or reboot
phase is authorized by this report.

Remaining original acceptance includes authenticated API and health, child sandbox/
cgroup/resource teardown, reviewed trusted-local-HTTPS update/no-update/checksum/
rollback/fresh retry, real boot/offline-lock attestation, repair/races and applicable
Linux core/UI suites. The existing full three-test systemd module still requires
actual prior-boot attestation; no prior ID may be invented. Parent Task 5 and
production readiness remain incomplete; controller owns review and further scope.

## Code-only follow-up

The [readiness-only runner follow-up](2026-10-30-installed-repair-readiness-only.md)
removes the strict xfail, shares production's API-health URL/transport, rejects the
consumed repair dispatch, and adds a separately approved known-installed-state
readiness phase. This does not amend the historical runtime outcome above: no
actual API-health response or new guest/service effect is claimed or authorized.
