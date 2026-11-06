# Active Release Virtualenv Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let an administrator safely rebuild the active transactional release's Python environment when the updater cannot start its normal preflight.

**Architecture:** Let a transactional release with a missing venv reach an actionable recovery branch instead of exiting at the early completeness guard. Add a focused helper, invoked as `knxohui`, that verifies the current release and acquires the updater lock before recreating that release's venv at its final path; on failure, restore any previous venv directory.

**Tech Stack:** Bash, Python 3.12+, standard-library path helper, `venv`/pip, pytest.

**Spec:** `docs/superpowers/specs/2026-11-06-pr69-active-release-venv-recovery-design.md`

## Global Constraints

- Resolve the active application from the canonical `current` symlink and reject targets outside `INSTALL_DIR/releases/`.
- Run environment creation and dependency installation as `knxohui`, not as root.
- Use the same data-directory `updater.lock` as `update.sh` to prevent repair from racing an update.
- Create the environment at `$APP_DIR/venv`; do not move a completed venv because entry-point shebangs contain its creation path.
- On repair failure, restore any prior venv directory and leave the active pointer unchanged.
- Keep legacy-install recovery and normal successful updates unchanged.
- Add no Python dependencies.

## Review Focus

- A present release directory with a missing or unusable `venv/bin/python` must reach actionable recovery, while a missing release directory still fails closed; paths containing spaces must remain one argument and the command must specify `sudo -u knxohui` (`test_transactional_update_missing_venv_emits_repair_command`, `test_transactional_update_unusable_venv_emits_repair_command`, `test_transactional_update_missing_release_fails_closed`).
- An executable but broken active interpreter must fall back to the stable worker so the Bash updater can print recovery (`test_update_worker_falls_back_when_active_python_is_broken`).
- A stale/current pointer or target outside `INSTALL_DIR/releases/` must be rejected without creating or changing venv files (`test_repair_release_venv_rejects_stale_or_unsafe_release`).
- A held updater lock must prevent venv changes (`test_repair_release_venv_refuses_busy_updater_lock`).
- Dependency-install failure must restore a previous partial venv and never change `current` (`test_repair_release_venv_restores_previous_venv_after_failure`).
- A successful repair must install at the final path, be safe to repeat, and allow a subsequent updater run to pass the missing-venv check (`test_recovery_command_repairs_active_venv_and_retry_passes_preflight`, `test_repair_release_venv_is_idempotent`).

---

### Task 1: Repair the active release venv safely

**Files:**
- Modify: `update.sh`
- Modify: `installer/launch_update.sh`
- Create: `installer/repair_release_venv.sh`
- Test: `tests/test_privilege_policy.py`
- Test: `tests/test_repair_release_venv.py`

**Interfaces:**
- `launch_update.sh` probes the selected Python interpreter and falls back to the stable worker if the active release interpreter cannot run.
- `update.sh` constructs `VENV_RECOVERY_COMMAND` as `sudo -u knxohui bash ` plus Bash `printf %q` of `$APP_DIR/installer/repair_release_venv.sh`; a missing or import-broken active environment uses this recovery command.
- `repair_release_venv.sh` derives its release root from its own location, resolves `install_dir` and `data_dir` through `knxoh_paths.get_paths()`, validates that `current` resolves to this release, and holds `$data_dir/updater.lock` for the rebuild.
- The helper rebuilds `$APP_DIR/venv` from `$APP_DIR/requirements.txt`, validates it with `pip check`, and restores any prior venv if a command fails.

- [x] **Step 1: Write failing updater and helper regressions**

Add the named tests in Review Focus. The updater integration case creates a transactional install whose `current` release has `update.sh` and `installer/` but no venv, asserts that the early guard no longer exits without guidance, shell-parses the emitted command, executes its helper through a test `sudo -u` shim, and retries the updater to prove it passes the venv check. A launcher regression covers an executable but broken current interpreter falling back to the stable worker. Helper tests cover stale targets, a busy lock, and rollback after simulated dependency-install failure.

- [x] **Step 2: Run the new tests to verify they fail**

Run: `pytest tests/test_privilege_policy.py::test_transactional_update_missing_venv_emits_repair_command tests/test_privilege_policy.py::test_transactional_update_unusable_venv_emits_repair_command tests/test_privilege_policy.py::test_update_worker_falls_back_when_active_python_is_broken tests/test_repair_release_venv.py -q`
Expected: FAIL because the current early guard exits before printing recovery and the repair helper does not exist.

- [x] **Step 3: Add active-release recovery and guarded venv rebuilding**

Permit an existing active release directory to reach the venv-specific recovery branch. Probe the current interpreter in `launch_update.sh` and fall back to the stable worker if it cannot execute. Escape the helper path with `printf %q`, invoke it as `knxohui`, and implement active-target validation, lock acquisition, final-path venv creation, dependency validation, and rollback of a prior venv on failure.

- [x] **Step 4: Run focused tests, shell syntax, and style checks**

Run: `pytest tests/test_privilege_policy.py tests/test_repair_release_venv.py -q`
Expected: all recovery and privilege-policy tests pass.

Run: `bash -n update.sh installer/launch_update.sh installer/repair_release_venv.sh`
Expected: no output and exit status 0.

Run: `black --check tests/test_privilege_policy.py tests/test_repair_release_venv.py && isort --check-only tests/test_privilege_policy.py tests/test_repair_release_venv.py && flake8 tests/test_privilege_policy.py tests/test_repair_release_venv.py`
Expected: no formatting/lint errors.

- [ ] **Step 5: Commit**

Use commit message: `fix: repair missing active release environments`.
