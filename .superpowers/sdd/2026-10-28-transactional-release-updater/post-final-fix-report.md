# Post-final focused corrections (base 237c7c4)

Scope: NB1, NB2, M1, M2 only; sequential TDD. No live service, user,
policy, mount, WSL-global, acceptance-runner, generated-output or UI changes.
Controller owns disposable WSL acceptance and the single final full-suite run.

## Test command environment

Unless explicitly noted, commands below use this exact PowerShell wrapper:

```powershell
wsl -d Ubuntu -u root -- bash -lc 'export PATH=/mnt/c/Users/Username/AppData/Local/Temp/opencode/knx_to_openhab-issues/.superpowers/sdd/2026-10-28-transactional-release-updater/linux-venv/bin:/usr/sbin:/usr/bin:/sbin:/bin; ulimit -Sn 32768; COMMAND'
```

Only fixture-local files and injected service IO are used. Production checker
subprocess limit tests intentionally lower their own limits, not host limits.

## NB1 — clean first administrator recovery activation

- Red: `/home/ubuntu/pr39-review-fixes-wsl.LAjE6Z/.venv/bin/python -m pytest -q tests/test_update_post_final_fixes.py`
  (via `wsl -d Ubuntu -u root -- bash -lc 'COMMAND'`). Output: `1 failed in 1.63s`.
  Actual `execute_setup` -> `activate_services` -> actual `recover` with production
  `SystemdAdapter.verify_recovery_preconditions` refused active writers, entered
  rollback and attempted to stop the timer (test intentionally rejects that).
- Change: only boot recovery's protected no-journal/no-maintenance/no-gate path
  returns clean without inactive-writer checks. Offline recovery remains strict;
  every journaled path retains production inactive-writer checks before mutation.
  Malformed gate/maintenance/unknown journal regressions remain blocked.
- Green: `python -m pytest -q tests/test_update_post_final_fixes.py tests/test_update_final_fixes.py tests/test_update_recovery.py`
  -> `253 passed in 101.19s (0:01:41)`.
- Interfaces unchanged. Captured live UI/timer states and coherent pair retained;
  no stop/start writer jobs in the first component-only activation.
- Verification accounting: initial PATH quoting attempt returned no test output
  (not counted). Another attempt failed shell parsing (not counted). A run using
  unrelated `/home/ubuntu/pr39-review-fixes-wsl.LAjE6Z/.venv` gave `4 failed, 43 passed`
  because demoted children cannot traverse that private directory: three
  `test_recovery_reconciles_status_then_real_demoted_submitter_claims` cases and
  `test_unprivileged_password_hash_mode_and_root_refusal`. Correct local venv
  resolves these without permission changes. First correct-venv combined run
  timed out at 120s; `-x tests/test_update_recovery.py` identified
  `test_offline_refuses_active_writers_without_mutation` (`1 failed, 70 passed`);
  kept offline preconditions, then obtained the green run above.

## NB2 — isolated administrator checker descriptor budget

- Red: `python -m pytest -q tests/test_update_post_final_fixes.py -k fd_budget --tb=short`
  -> `4 failed, 4 deselected in 4.96s`. Actual isolated check-release CLI under
  inherited validated lease, soft=64/hard=32768 or 128; 256 valid immutable
  dependency files. Active repair wrongly warned predecessor guidance; inactive
  activation wrongly refused. Insufficient hard limits also produced legacy advice.
- Change: `check_existing_release` establishes/verifies soft 32768 within the
  existing hard budget before scanning. Never increases hard limits, never changes
  unit/host configuration. Insufficient budget/setrlimit failure and direct or
  fdinfo-wrapped EMFILE/ENFILE are explicit descriptor-resource errors, not
  predecessor advice. Tree ownership/link/mount validation is unchanged.
- Additional red: `python -m pytest -q tests/test_update_post_final_fixes.py -k misdiagnose --tb=short`
  -> `1 failed, 1 passed, 8 deselected in 2.75s` for wrapped exhaustion. Follow
  explicit exception causes for the resource diagnosis; do not weaken validation.
- Green: `python -m pytest -q tests/test_update_post_final_fixes.py tests/test_update_final_fixes.py tests/test_update_bootstrap_recovery.py --tb=short`
  -> `61 passed in 40.40s` (earlier budget-only implementation: `59 passed in 23.32s`).
  One mistyped filename `tests/test_update_bootstrap.py` yielded `no tests ran`;
  corrected to `tests/test_update_bootstrap_recovery.py` above.
- Public interfaces/CLI unchanged. Resource insufficiency now blocks repair rather
  than permitting a misleading predecessor warning; active pair and config remain
  unchanged. Subprocess tests cover active repair and inactive activation without
  executing candidate code or provisioning anything.

## M1 — late pinned public-status replacement classification

- Red: `python -m pytest -q tests/test_update_post_final_fixes.py -k last_entry_check --tb=short`
  -> `2 failed, 2 passed, 10 deselected in 2.54s`. Deterministic atomic replacement
  after the final `_check` and before `fstat` yielded plain ValueError instead of
  successful bounded retry; repeated late replacements also failed without retry.
- Change: on final size/mtime/ctime mismatch, recheck the pinned entry/chain before
  raising generic concurrent-content failure. Known entry replacement now raises
  EntryChangedError; oversized data and in-place content mutation remain ordinary
  validation failures. No new retry loop or relaxation of ownership/link/mount rules.
- Green: `python -m pytest -q tests/test_update_post_final_fixes.py tests/test_update_final_fixes.py tests/test_update_secure_fs.py --tb=short`
  -> `110 passed in 21.14s`. Covers late replacement, three-attempt churn bound,
  unsafe replacement rejection, in-place modification refusal, and previous race/
  secure filesystem regressions. Public interfaces unchanged.
