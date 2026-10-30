# Existing hostile probe blocked before transport — 2026-10-30

**BLOCKED; no hostile runtime acceptance PASS. Parent Task5 remains OPEN.**

After readiness PASS290c010, the controller authorized only the existing reviewed
probe using installed repaired production `2dcf3078b61283a41fd1ef38e34327e4f759d5c1`
and its unchanged pinned source approval. All five runner files byte-match reviewed
`2fcaf29`; hostile integration fixture and SystemdAdapter also byte-match `d1f1848`.

The exact `--phase probe --source-approval ... --approved-source-head 2dc...`
command exited1 locally before registration, preflight, guest transport or evidence
directory creation:

```text
run_nested_systemd_acceptance.py:118 -> nested_fixture_state.py:405
ValueError: Reviewed source identity/approval mismatch
```

Probe's old validator requires `reviewed-sudo-fix-source` based on `27d106a`.
The adopted installed-repair manifest correctly uses
`reviewed-environmentfile-fix-source` based on `47e2c3a`. Guest probe's
`verify_source_approval` calls the same incompatible validator, so changing only
the controller would not resolve the contract. No approval was rewritten,
legacy-labeled, repinned or bypassed; no runner or production fix was made.

An offline regression reproduced the desired-path failure: **1 failed, 2 passed**.
Passing controls prove refusal before any registration/transport and reproduce the
same guest-validator mismatch. The deliberate RED reproduction is private, not
presented as a passing committed suite.

A separate guarded read-only diagnostic exited0/status0 and confirmed:

- Same live manager snapshot as readiness: UI active/running, cleanup timer
  active/waiting, updater inactive/dead, recovery active/exited; historical cleanup
  failed/status1 retained. No queued jobs, updater journal or child units.
- All3354 original release entries, configuration/credentials/external state,
  current target, exact repaired components and old retained bundle preserved.
- No candidate/workspace/request UUID was created. No adapter was instantiated,
  so there were no owned children to stop; no guessed/unrelated stop was attempted.

Private exact command, code hashes, RED regression, state report and raw evidence:
`wsl-acceptance/probe-execution-report.md` under the task's ignored scratch folder.
CLI log SHA-256:
`add51ac2b0b13c9ac52f010347395e361592ab514b07cb1e2abe9b4d642a8dea`.
Read-only end-state log SHA-256:
`4f5c1f7cba45c89e5b8658e0bc55ba52f25bb8c42e803be52bdd20cefa38b8f1`.

No readiness/repair/bootstrap rerun, restart, update, reboot, reset-failed, granted
sudo action, production change or broad cleanup occurred. No full/core/UI suite
was run. Worker UID/denials, actual installed worker execution, namespace/NNP,
heartbeat and whole-cgroup teardown remain **NOT VERIFIED**. Next work needs a
separately reviewed repair-source contract on both sides and explicit renewed
probe authorization; this evidence does not authorize implementation or rerun.
