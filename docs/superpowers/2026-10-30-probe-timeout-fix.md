# Hostile probe timeout: acceptance-only fix — 2026-10-30

**Fixed offline only. Original real probe exit1 is unchanged; no runtime retry.**

Base: `a406421`. The root cause and actual security evidence remain recorded in
`2026-10-30-probe-runtime-timeout-blocker.md`. The production adapter is correct:
the deliberately SIGTERM-ignoring descendant requires SIGKILL after the existing
15s stop deadline, making the migration operation fail (`Result=timeout`, main
exit0). This is an assurance test of confinement/termination, not update success.

Only `tests/integration/test_update_systemd.py` acceptance handling changed, with
portable regression tests and documentation. No production/adapter/runner/provider
code, installed unit, timeout, approval or hostile candidate bytes changed.

The callback now requires all of:

- Exact own UUID/migrate `systemd-run --wait` exit1 and exact helper/stage/paths.
- Successful internal stop proof; exact loaded failed unit, timeout/main exited0,
  zero main/control PIDs, 15s stop timeout, empty ControlGroup, absent cgroup.
- Read-only live `/proc`/cgroup capture before cleanup: actual installed helper
  and candidate execution with worker UID/GID, NNP1, five empty capability sets,
  distinct live mount/network namespaces and loopback-only interface/route evidence.
  Pre-exec setup tasks do not substitute for actual helper execution.
- Own unit's PID-1 journal SIGKILL of the observed SIGTERM-ignoring candidate;
  all observed PIDs absent, all five exact live-state reads denied, failed sudo,
  bounded probe output and stable nonempty heartbeat before PASS.
- Mandatory outer `stop_children` for all five stages on success or any failure,
  including evidence/operation failures. Cleanup failure prevents PASS.

Missing evidence, unexpected operation success, unrelated/nonzero command errors,
wrong result/main status/identity, failed stop or surviving cgroup/PID still fail.
The result label is **expected operation failure; confinement/termination PASS**.
No failed production migration is accepted or ignored.

## Offline verification

The two key replay cases against the original `a406421` callback produce
**1 failed, 1 passed**: expected timeout aborts at original line322; an unrelated
operation exception still triggers all-stage cleanup. Against the corrected
callback both pass. They run the real production adapter with scripted manager
I/O and nonzero operation outcomes, not a success-returning replacement adapter.
Additional negative cases and a real local proc-file reader exercise strict
evidence validation. These are portable replays, not new runtime evidence.
The focused portable run completed **418 passed, 8 skipped** (five POSIX-only
venv cases and three unconfigured real-systemd cases). This includes all 31 new
acceptance-replay/reader cases. Black, isort, flake8 on both changed Python files
and `git diff --check` passed. No full native core or live/UI run is implied.

Private `wsl-acceptance/probe-timeout-fix-report.md` retains exact commands/results,
historical RED comparison, local self-review and verification limits. No private
logs, receipts, approvals or secrets are committed.

## Runtime handoff remains gated

No guest transport/manager/application command, update, readiness, repair, reboot,
reset-failed or cleanup deletion occurred. Previous failed unit/candidate/workspace
and original private logs remain untouched. The historical actual probe and
observer each remain exit1; the later read-only diagnostic remains exit0. The
recorded UI/timer/API/3354-entry preservation evidence was not re-observed here.

The nested runner still imports `/opt/knxoh-harness-d1f1848`; editing this checkout
does not adopt the new callback in that guest. Independent controller review must
cover callback adoption and the new read-only observation, then explicitly
authorize ONE new UUID/runtime attempt with all original guards. Missing a short
helper sample fails closed and never implies permission to retry. Parent Task5,
full installed update/rollback/reboot and remaining acceptance stay open. No full
native core or UI suite was run, as explicitly scoped by the controller.
