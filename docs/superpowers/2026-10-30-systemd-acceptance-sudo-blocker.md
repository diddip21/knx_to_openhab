# Real nested acceptance: provisioning blocked by sudo listing semantics

**BLOCKED, not accepted.** Guard review of `d1f1848` approved proceeding. Current
read-only outer/inner preflight and the actual pinned root-receipt guard passed.
Real fixture provisioning then exposed a production bootstrap refusal before any
application unit, updater bundle, release environment or application was installed.
Production source remains immutable `27d106a`; no production fix was made.

## Observed production failure

Inside the authorized Ubuntu 24.04 nested guest, sudo **1.9.15p5**, UID/EUID/GID/EGID
all **0**, `NoNewPrivs: 0`, and the production's minimal C locale/environment:

```text
/usr/bin/sudo -n -l -U knxohupdate
returncode: 0
stdout: User knxohupdate is not allowed to run sudo on localhost.\n
stderr: (empty)
```

The actual worker is a distinct nologin identity with only its own group:
`knxohupdate` UID 997/GID 988/groups `[988]`; UI UID 999/GID 989/groups `[989]`.
Production `check_worker()` succeeds. Production `check_worker_sudo()` requires
exit **1**, so it refuses the observed complete denial with:

```text
Cannot prove knxohupdate has no direct sudo grants; repair administrator policy
```

Repeated read-only queries and a real Linux pytest regression reproduce this.
This is not an NNP-confined sudo attempt, an executed permitted action, an
ambiguous stderr error, a fake manager state, or a worker grant. No check was
bypassed and no sudo policy was changed. A future correction must still reject
grants and ambiguous/error responses; exit zero alone is not sufficient evidence.

## Reproduction

The approved harness is separately deployed at `/opt/knxoh-harness-d1f1848`:
241 native LF-archive files hash-verified, root-owned, with mode-0600 provider
receipt installed and validated through its actual pinned reader. Production
source is separately retained at `/opt/knxoh-source-27d106a` (238 verified files).
No new prior-boot or offline-lock attestations were invented.

From the native Windows checkout, with the existing private provider receipt:

```powershell
python scripts/run_nested_systemd_acceptance.py --receipt <private-provider-receipt.json> --evidence-dir <private-evidence-dir> --phase sudo-regression
```

The runner revalidates exact registration, outer and inner identities, integration
and mount policy before invoking only the explicitly named nested machine. It
then authenticates the root receipt/live inner evidence before the read-only test.
Result on the real guest: **1 failed**, at production `check_worker_sudo()`.
The test is `tests/integration/test_update_sudo_runtime.py`; ordinary collection
skips it unless explicitly opted in. It executes real sudo queries, never an
allowed sudo action. This is a deliberate RED regression, not a passing release.

`scripts/nested_systemd_fixture.py` contains the guarded fresh-only bootstrap
phase used for the attempt and a later hostile-child probe phase. Only the
bootstrap prefix through `provision_worker()` ran. Bundle/venv/service-start and
hostile-child code remains **unexecuted**, not verified by its presence. The
initial-environment code uses the verified source and approved wheel-only offline
dependencies; it must never be reused to execute a worker-produced venv as root.

## Retained safe state and next step

- Only the fresh outer distribution's own nested guest was changed. Existing
  Ubuntu/Windows state, default WSL distribution, mounts and interoperability were
  not changed. No machine reboot occurred; the recorded inner boot ID is unchanged.
- Fixture-owned UI/worker accounts, custom directories containing spaces, initial
  config/generator/paths files and a local inner hostname mapping exist.
- No application units, installed updater bundle, release/current, application
  secrets, sudoers change or release venv exists. The root-owned mode-0600
  lifecycle lock is retained and was independently found acquirable, never unlinked.
- Raw logs, source/harness manifests, root receipt/nonces and exact commands stay
  in ignored `.superpowers/sdd/2026-10-28-transactional-release-updater/wsl-acceptance/`;
  see `wsl-acceptance-report.md`, `sudo-regression.log`, `sudo_diagnostic.log`, and
  `blocked_state.log`.

Controller action: correct/review the production listing validation, then authorize
an explicit guarded continuation of this recorded partial fixture (or a separate
fresh fixture). The fresh-only runner intentionally refuses existing paths/accounts;
do not delete them, blindly repeat bootstrap, grant worker sudo, fake exit status,
or edit the immutable baseline to get past the failure.

Runner-review corrections and the explicit **`resume-after-sudo`** protocol are
specified in [`2026-10-30-acceptance-continuation-design.md`](2026-10-30-acceptance-continuation-design.md).
That route requires the exact recorded checkpoint plus out-of-guest pins for it
and a separately reviewed new production source. It never repeats fresh seeding.
No continuation/enrollment/preflight ran while implementing that revision; both
runner and production reviews precede runtime authorization.

All full installed-unit update/rollback, actual worker isolation/cgroup teardown,
readiness, production-dependency lifecycle, real boot/offline-lock ordering,
resource/repair acceptance and original three systemd tests remain outstanding.
Parent Task 5 remains incomplete and requires controller review.

Verification for this acceptance-runner change:

- Real nested Linux regression: **1 failed** (production refusal reproduced).
- Focused native dispatch/existing worker-policy tests: **7 passed, 3 skipped,
  49 deselected**; skips are live opt-in and two Linux-only filesystem cases.
- Black/isort/flake8 on all **141 tracked/new Python files**: passed.
- No full core/UI rerun or real application acceptance is claimed.
