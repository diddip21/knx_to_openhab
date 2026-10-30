# Readiness-only runtime evidence — 2026-10-30

**READINESS PASS (narrow scope); parent Task5/full production acceptance OPEN.**

After independent review and explicit controller adoption of private inputs, the
[reviewed readiness-only command](2026-10-30-installed-repair-readiness-only.md)
ran once using runner `2fcaf2976eebd6a57b71a28fafd0f431f7e922b1` and installed
production `2dcf3078b61283a41fd1ef38e34327e4f759d5c1`. The historical checkpoint
was preservation evidence only, not another repair authorization.

- Actual guarded nested phase exited0/status0. Current registration, original
  receipt/identity/mount isolation, complete source maps, original paths, full
  preservation and pinned stopped-manager/component checks passed, repeated under
  the retained lifecycle lease. Lease release preceded production activation.
- Actual production activation performed daemon-reload, start of already-active
  recovery, own notify UI restart and own cleanup-timer start. No installation,
  configuration, credential, venv or release changes, reset-failed or updater run.
- Production's direct-listener/no-proxy/no-redirect helper accepted exactly
  `{"status":"ready","version":"0.1.0"}` from
  `http://127.0.0.1:8085/api/health`. One subsequent read-only diagnostic confirmed
  the same JSON; actual UI access journal contains both HTTP200 requests.
- Loaded UI is `Type=notify`, `NotifyAccess=main`, active/running, MainPID105534,
  result/status success/0. Cleanup timer active/waiting; cleanup service's historical
  failed/exit-code/status1 remains intact. Updater inactive/dead; recovery retains
  its prior active/exited/success invocation. Own queued jobs empty.
- Pre-activation UI NRestarts19 passed exact pinned-state checks; activation and
  final snapshots show0 after the authorized normal restart. No reset-failed was
  called; the counter is not claimed unchanged or adopted as new original history.
- Read-only postactivation verification preserved all **3354** initial entries,
  metadata/inodes/current target, full external/configuration/credential/lock
  identities, exact repaired components and retained old bundle. No updater journal.

Private incremental report: `wsl-acceptance/readiness-execution-report.md` beneath
the task's ignored scratch directory. Exact command, actual unit states, full
private output hashes and verification receipts are retained there. Main phase
log SHA-256: `2c8abe3bdb81a142d9fdd356d44bdac7c983ff38c3d83eca7166eb7586b2da3e`.
Read-only diagnostic log SHA-256:
`ef41d5390e0ac08fa46c74b777bf2a89b5046641cc1c1938c3a39ebe96bacadb`.
No private approvals, raw logs, nonces or credentials are included in this delivery.

No retry, repair rerun, hostile probe, update or reboot followed success. Own UI
and timer remain active as authorized; only read-only diagnostics followed.
No code changed and no core/UI/portable suite was rerun for this operational step.
Real update/no-update/checksum/rollback/fresh-retry, authenticated API,
sandbox/cgroup/resource teardown, real boot/offline-lock attestation, repair/races
and applicable Linux/core/UI suites remain separate obligations. Further runtime
effects require the controller's next known scope; this is not full readiness.
