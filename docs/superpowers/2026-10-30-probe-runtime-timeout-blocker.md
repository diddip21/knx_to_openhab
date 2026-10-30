# Actual hostile probe: isolation verified, acceptance blocked — 2026-10-30

**BLOCKED; actual command exit1. Parent Task5 remains OPEN.**

Following independent approval of `bc59dbe` and explicit one-command authorization,
the unchanged reviewed probe ran once against installed repaired production2dc
using the original approval. Fresh guards passed; no source/approval rewrite,
bootstrap, repair/readiness rerun, activation, update, reboot or reset-failed.

## Actual failure

The root-installed `update_prepare.py` ran unprivileged and exited0. The reviewed
hostile candidate deliberately forked a SIGTERM-ignoring writer. After15s systemd
SIGKILLed that descendant, removed its cgroup, and recorded `Result=timeout`.
`systemd-run --wait` therefore returned1. The fail-closed production adapter
propagated it; the hostile acceptance callback aborted at line322 before its
evidence assertions. Its mandatory outer `stop_children` finally still ran.

This is an acceptance control-flow mismatch, **not permission to accept failed
migrations in production**. No fix, policy relaxation or actual probe retry followed.

## Real evidence obtained

- Installed helper, candidate and fork observed at UID997/GID988, NNP1, empty
  capabilities. Actual candidate bytes match the unchanged reviewed hostile fixture.
- Config, credentials, live data, backups and private updater-state reads denied;
  worker sudo returned1. Repaired-source outside-NNP account/sudo-listing gates
  passed before execution; no granted package action was executed.
- Actual `/proc/PID/ns` mount AND network namespaces differ from the observer.
  Worker/fork route/interface observations show loopback only, no IPv4 routes and
  IPv6 entries only on loopback. This is live proof, not a property-only inference.
- Journal identifies the actual ignoring fork's SIGKILL. All observed PIDs gone;
  cgroup absent; all five stages' ControlGroup empty; retained heartbeat stable.
  Failed migrate unit remains intact, result timeout/main exit0.
- UI and timer unchanged active; updater inactive; recovery active/exited;
  historical cleanup failure retained. API health ready/version0.1.0. All3354
  original release entries, external configuration/credentials, current target,
  installed components and old retained bundle preserved.

The read-only observer's final immutable-tree inventory also refused newly
worker-owned probe output, as designed. That failure is retained, not hidden.
A separate guarded read-only diagnostic collected final evidence and verified
preserved trees excluding only the authorized unique candidate/workspace and their
proven parent-directory additions. No ownership, policy or collector was modified.

## Retained evidence and limits

The unique candidate/workspace, probe output and failed unit remain for review.
Incremental private report, exact command, code hashes, namespaces, journal,
show/cgroup/PID evidence and preservation receipts are under
`wsl-acceptance/probe-execution-report.md` and `probe-execution-bc59dbe/` in ignored
task scratch. Original offline refusal history is preserved.

- Actual probe log SHA-256:
  `a9aeeeb84995d422478666357ff113ea03f1f5a42f4c97bb16603da9c13c4344`.
- Actual final read-only log SHA-256:
  `56b831b8fd01c17c16b454ff5f111a3808483094bb0406faa79dc144d6cbb010`.
- Narrow offline evidence-replay regression: **1 failed, 1 passed**. It reproduces
  the callback abort and preserves the finally-cleanup control; it is NOT a second
  runtime attempt or a passing committed suite. No full/core/UI suite was run.

No private logs, receipts, approvals, nonces or secrets are committed. No production
code changed. Next work needs a separately reviewed narrow acceptance fix and fresh
runtime authorization; no automatic retry. Update/reboot acceptance remains open.
