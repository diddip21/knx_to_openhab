# Actual hostile confinement probe passed — 2026-10-30

**One separately authorized actual probe passed, exit0. Full update and boot
acceptance remain OPEN.** No production code was changed.

This follows the retained historical failure described in
[the earlier timeout report](2026-10-30-probe-runtime-timeout-blocker.md).
That earlier probe and observer still failed; their evidence was not rewritten.
The new run used a new unique request, not an automatic retry.

## Verified execution boundary

The separately reviewed harness was exclusively deployed and its complete
269-file inventory verified. A separate fresh-interpreter observation verified
actual callback and adapter code origins before the actual probe.

The reviewed explicit dispatcher selected the new harness before trusted imports.
Current original-provider, guest receipt/identity, exact fixture paths/preparation,
original repaired production source, installed-helper and outside-NNP worker/sudo
guards all passed. Neither production source nor installed components were
replaced to run the test.

## Actual confinement and termination evidence

- Installed helper, candidate and descendant were independently observed at
  UID997/GID988, NoNewPrivileges1, with all five capability fields zero.
- Actual mount and network namespaces differed from the observer. Network
  observations showed loopback only, no IPv4 routes and only loopback IPv6 entries.
- The exact five protected live-state reads were denied; worker sudo returned1.
- The hostile descendant deliberately ignored SIGTERM. PID1's own-unit journal
  identified its SIGKILL after the unchanged15-second stop timeout.
- The migrate unit remained failed with Result=timeout and main exit0. The
  callback required that exact expected operation failure plus independent proof;
  a successful main process alone could not pass.
- All observed PIDs disappeared, the own cgroup was absent and heartbeat output
  stopped changing. Mandatory finally cleanup completed for all five stages.
- The actual callback printed confinement/termination PASS. Its controller exited0;
  a separate guarded read-only end-state observation also exited0.

**This is successful hostile confinement/termination acceptance, not a successful
migration.** The unchanged production adapter still propagates operation failure.

## Preservation and evidence limits

Before/after direct observations confirmed all3354 initial-release entries,
protected config, generated output and11 installed bundle hashes unchanged. UI
manager state/PID and active timer were unchanged; direct API health returned
HTTP200, ready/version0.1.0. No application unit operation or updater ran.

The prior historical artifact pair remained unchanged. Its worker-owned output is
not an immutable-root application tree or recovery authority. The additional
baseline collector's ownership refusal was diagnosed without changing validation.
Old and new request artifacts were observed separately, with bounded no-follow
worker-output reads and strict protected-file readers. No full filtered-collector
acceptance is claimed. Only the exact new request's release/preparation additions
and corresponding parent link-count increments were accounted for.

Private exact commands, origins, live proc evidence, journal, five-stage state,
preservation comparisons and artifact hashes are retained in the ignored task
scratch execution report and evidence directory. No private pins, receipts, logs,
nonces, credentials or secrets are committed.

No repair/readiness rerun, ownership change, reset-failed, dependency installation,
application deployment, reboot or unrelated full test suite occurred. Full
installed update/no-update/checksum/rollback/retry, actual reboot/offline-lock and
remaining API/core/UI acceptance are not established. Parent Task5 remains OPEN.
