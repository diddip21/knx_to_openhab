# Installed repair: readiness-only follow-up (code review, NOT runtime authorization)

## Scope and design

The authorized 2dcf3078 installed-component repair succeeded. Its EnvironmentFiles
regression passed twice; notify UI activation succeeded, but the runner requested
`/health` and received 302. There is still **no actual `/api/health` proof**.
See [the retained blocker](2026-10-30-repair-health-endpoint-blocker.md).

This changes only the acceptance runner, tests and documentation. No production,
UI, configuration, credential, venv or checkpoint changes. No guest operation or
service start is authorized by this delivery.

The narrow approach is to reuse production `health_url` and `fetch_health`, not
duplicate the endpoint, HTTP client, JSON decoder, proxy policy or redirect policy.
The runner requires exactly `{"status":"ready","version":"0.1.0"}` from that
direct listener. The portable contract also calls the actual Flask route with auth
enabled and sessions forbidden; no replacement Flask application is constructed.
Following 302, falling back to `/health`, or injecting credentials/environment is
not readiness. The previous strict xfail is removed, not hidden or weakened.

The only new transition is **`--phase readiness-only`**. It is not bootstrap,
after-sudo continuation, or another EnvironmentFile repair. The consumed
`repair-environmentfile` phase is now unconditionally rejected by CLI, transport
and guest dispatcher, even when supplied its old approved inputs.

## Pure validation before activation

The historical checkpoint is reused as evidence, never matched as a reusable
pre-install state. Existing source and post-install validators recheck:

1. Current provider registration/preflight, original inner receipt, machine/boot.
2. Exact original FixturePaths, decoded with production's read-only loader.
3. Full verified old source and exact production
   `2dcf3078b61283a41fd1ef38e34327e4f759d5c1` source approval.
4. Original external inventory, current target, all **3354** initial entries and
   original configuration/credentials/locks. No unrelated state adoption.
5. Exact new installed component bytes/renderer and exactly retained old bundle
   bytes, metadata and inodes, using existing `verify_repaired`.
6. Separately controller-pinned repaired-component identity hash, including the
   retained bundle. This hash covers only replaceable components and retained
   bundle entries; it does not enroll a new full filesystem snapshot.
7. Separately pinned current stopped-manager state with no own queued jobs.
   Relative to the original manager receipt, only the UI's ActiveState/SubState,
   Result and ExecMainStatus may become inactive/dead/success/0. MainPID stays 0;
   NRestarts (19), UnitFileState, cleanup's historical failure, updater and recovery
   state cannot be reapproved as new history. Cleanup timer was stopped both
   originally and after the runner's failure handler.

Checks repeat under the retained original lifecycle inode/lease. Its existing
production installer-lease validation is read-only and refuses maintenance/gate
state. Preservation against the original empty updater-state directory additionally
requires **no journal at all**, not merely a terminal journal. No provisioning,
component install, venv execution, lock replacement or checkpoint write is called.

Release the lease before invoking the actual verified production
`activate_services`: daemon-reload, start already-active/exited recovery (no-op),
restart own UI, start own cleanup timer, then direct API health. No enablement
change, cleanup-service rerun, reset-failed or updater invocation. Activation or
health failure stops only own UI/cleanup writers and prints retained manager
evidence; no repair, retry, fallback or recovery workaround follows.

## Additional controller approval (NOT generated here)

Use the existing pinned checkpoint and production source approval. Add one private
`readiness-approval-PENDING.json`, with exactly these top-level keys:

- `state`: `format: 1`, `phase: "readiness-only"`, original `nonce_sha256`, the
  exact retained `manager` object, and `components_sha256`.
- `runner_files`: SHA-256 of the **actual current file bytes** of all five names
  in `READINESS_RUNNER_FILES`. Pin the reviewed commit separately in controller
  records. Current code is transported in memory using the existing trusted
  transport; no old immutable guest harness tree is edited or replaced.
- `evidence_files`: exact controller-local paths and SHA-256 pins for the existing
  `repair-environmentfile.log`, `installed-green.log`, and `diagnostic.log` under
  private `repair-execution-829992f/`. Controller review must adopt these as the
  successful disk repair, two installed-writer passes, and preservation receipts;
  the old whole-phase exit 1 is **not** represented as readiness success.

The runner verifies all these external file pins before provider dispatch. The
controller must review/pin the stopped state and component identity; if a narrow
read-only collection is needed, authorize that separately first. There is no
automatic receipt generator, approval flag or full-snapshot enrollment here.
No new readiness approval or SHA pin has been created/adopted in this task.

## Proposed command — only after controller review and explicit effect approval

PowerShell, from the reviewed checkout. Replace the one placeholder with the
controller's externally approved digest; do not infer it from a fresh observation.
Use a new evidence directory, preserving all prior logs.

```powershell
$scratch = '.superpowers/sdd/2026-10-28-transactional-release-updater/wsl-acceptance'
python -B scripts/run_nested_systemd_acceptance.py `
  --phase readiness-only `
  --receipt "$scratch/provider-receipt.json" `
  --checkpoint "$scratch/collector-contract-c0e381c/installed-checkpoint-PENDING.json" `
  --checkpoint-sha256 94194c4e32dfd63a6518adc09f2feab88ae0175081ae337a203b2b8274d599d7 `
  --source-approval "$scratch/repair-pins-c0e381c/source-approval.json" `
  --source-approval-sha256 90936a02e1fa20d124e427e45bd466957f86f379aa15badd0290bbcdc84cafea `
  --approved-source-head 2dcf3078b61283a41fd1ef38e34327e4f759d5c1 `
  --readiness-approval "$scratch/readiness-approval-PENDING.json" `
  --readiness-approval-sha256 '<CONTROLLER_APPROVED_READINESS_SHA256>' `
  --evidence-dir "$scratch/readiness-only-reviewed-run-01"
```

This command has **not** been run. No hostile probe, update, reboot, corrupt-journal
phase or final Linux/core/UI acceptance is authorized here. Parent Task 5 and
production readiness remain incomplete until actual runtime evidence and review.

## Native verification (no guest effects)

- Removed strict xfail first: **1 failed in 0.18s**, showing the original
  `/health` versus `/api/health` mismatch before changing the runner.
- Focused repair/health tests after implementation: **139 passed in 83.90s**.
- Final six-module portable nested-harness suite, including additional path,
  manager-history, redirect and health-failure cases: **312 passed in 91.78s**.
- Black `--check`, isort `--check-only`, flake8 on all five touched Python files,
  and `git diff --check`: exit 0. Git only reported local LF/CRLF conversion warnings.
- No full Windows core suite, UI suite, Linux suite or live guest/service test was
  run. No runtime readiness claim follows from these native tests. Controller code
  review and explicit effect authorization remain mandatory.
