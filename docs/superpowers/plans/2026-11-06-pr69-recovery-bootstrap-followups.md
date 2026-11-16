# Active Release Recovery Bootstrap Follow-Up Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make active-release venv recovery work independently of release-local helper files and reliably through the supported installer/bootstrap path.

**Architecture:** Install a stable repair helper and the worker launcher under `/usr/local/libexec/knx_to_openhab` from `setup.sh`. The helper receives installation paths explicitly, takes the updater lock before validating `current`, and repairs the active release. If the stable helper is not installed yet, `update.sh` recommends setup; setup installs both helpers and repairs a transactional active release before restarting services.

**Tech Stack:** Bash, Python 3.12+, `knxoh_paths`, systemd installer, pytest.

**Spec:** `docs/superpowers/specs/2026-11-06-pr69-recovery-bootstrap-design.md`

## Global Constraints

- Preserve existing defaults and support custom `KNXOH_PATHS_FILE` values.
- Pass install, runtime-data, configuration, backup, and paths-file locations explicitly across sudo boundaries.
- Use the existing `$DATA_DIR/updater.lock`; acquire it before validating the active release target.
- Continue to create the venv at the active release's final path as `knxohui`.
- Do not add sudoers capabilities, Python dependencies, or root writes to the web updater.
- Keep legacy setup behavior unchanged; skip active-release repair when no transactional `current` link exists.
- Refresh root-owned launch helpers only through `setup.sh`.

## Review Focus

- A stable helper must repair a release that has no release-local helper (`test_stable_repair_helper_recovers_release_without_local_helper`).
- A caller's custom paths-file value must survive sudo environment sanitization in both direct-helper and setup fallback commands (`test_recovery_command_preserves_custom_paths_under_sudo`).
- A pointer switch between initial helper invocation and lock acquisition must be rejected without creating a venv (`test_repair_revalidates_current_after_lock_acquisition`).
- When the stable helper is absent, recovery must print a quoted setup bootstrap command with all configured paths (`test_update_missing_stable_helper_recommends_setup_bootstrap`).
- Setup must install the root-owned helper and launcher and repair the active transactional venv before restarting the Web UI (`test_setup_installs_and_runs_stable_recovery_helpers`); legacy installs skip helper execution.
- The installed launcher—not only the source-tree script—must fall back when active Python is executable but unusable (`test_update_worker_falls_back_when_active_python_is_broken`).
- A pre-change updater cannot self-print new recovery instructions; document the one-time administrator bootstrap using `setup.sh` from updated source.

---

### Task 1: Make the repair helper stable-path and race safe

**Files:**
- Modify: `installer/repair_release_venv.sh`
- Modify: `update.sh`
- Test: `tests/test_repair_release_venv.py`
- Test: `tests/test_privilege_policy.py`

**Interfaces:**
- The stable helper consumes `KNXOH_INSTALL_DIR`, `KNXOH_DATA_DIR`, and `KNXOH_PATHS_FILE`, validates the resolved values using `$INSTALL_DIR/knxoh_paths.py`, and discovers the active app by resolving `$INSTALL_DIR/current`.
- `update.sh` prints a direct command using `sudo -u knxohui env` with shell-escaped assignments for install dir, data dir, paths-file, and the expected active release, followed by the stable helper path.
- The helper acquires `$DATA_DIR/updater.lock`, then resolves `current` beneath `$INSTALL_DIR/releases`, compares it with the expected active release, and only then repairs that release.

- [x] **Step 1: Write failing stable-helper regressions**

Add tests that run the helper from a stable libexec location while the active release has no local helper; simulate sudo dropping all `KNXOH_*` variables but preserving explicit `env` assignments; and use a `flock` shim to switch `current` immediately before acquiring the real lock. The stale target must be rejected and no venv may be created.

- [x] **Step 2: Run the new tests and verify the failures**

Run: `pytest tests/test_repair_release_venv.py::test_stable_repair_helper_recovers_release_without_local_helper tests/test_repair_release_venv.py::test_repair_revalidates_current_after_lock_acquisition tests/test_privilege_policy.py::test_recovery_command_preserves_custom_paths_under_sudo -q`
Expected: FAIL because the helper is release-local, the command omits path assignments, and current is checked before the lock.

- [x] **Step 3: Implement explicit-path stable repair**

Resolve paths from the explicit environment plus the stable install's `knxoh_paths.py`, require absolute canonical paths, acquire the shared lock before validating `current`, and use the resolved active release's requirements and final venv path. Print an escaped direct helper invocation from `update.sh`.

- [x] **Step 4: Run helper and direct-command focused tests**

Run: `pytest tests/test_repair_release_venv.py -q`
Expected: all helper recovery, rollback, locking, and path-sanitization tests pass.

- [x] **Step 5: Commit**

Use commit message: `fix: stabilize active release repair helper`.

### Task 2: Bootstrap helper and launcher through setup

**Files:**
- Modify: `installer/setup.sh`
- Modify: `update.sh`
- Modify: `tests/test_privilege_policy.py`
- Modify: `tests/test_repair_release_venv.py`
- Modify: `docs/PRODUCTION_GUIDE.md`

**Interfaces:**
- `setup.sh` honors `KNXOH_PATHS_FILE`, installs both root-owned scripts into `/usr/local/libexec/knx_to_openhab`, and invokes the stable repair helper as `knxohui` for an existing transactional current release before restarting the Web UI.
- If the stable helper is missing, `update.sh` prints a shell-safe `sudo env ... bash $APP_DIR/installer/setup.sh` bootstrap command carrying `KNXOH_INSTALL_DIR`, `KNXOH_CONFIG_DIR`, `KNXOH_DATA_DIR`, `KNXOH_BACKUP_DIR`, and `KNXOH_PATHS_FILE`.
- The setup fallback must repair the active venv itself; the user need not manually find or invoke a second script.

- [x] **Step 1: Write failing setup/bootstrap and installed-launcher regressions**

Assert the fallback setup command shell-parses to the expected paths even with spaces; assert setup installs the stable helper and launcher and calls repair before the Web UI restart; and execute a temporary installed copy of `launch_update.sh` against a broken active interpreter to prove fallback. Include a legacy setup assertion that active repair is conditional on `current` being a symlink.

- [x] **Step 2: Run the new tests and verify they fail**

Run: `pytest tests/test_privilege_policy.py::test_update_missing_stable_helper_recommends_setup_bootstrap tests/test_privilege_policy.py::test_setup_installs_and_runs_stable_recovery_helpers tests/test_privilege_policy.py::test_update_worker_falls_back_when_active_python_is_broken -q`
Expected: FAIL because setup does not install/call the stable repair helper, does not honor a custom paths-file environment variable, and the setup fallback command is not emitted.

- [x] **Step 3: Install and invoke stable recovery artifacts from setup**

Make `PATHS_FILE` honor `KNXOH_PATHS_FILE`; install the stable helper and updated launcher with root ownership; call the stable helper as `knxohui` before restarting services when `current` is transactional; make `update.sh` recommend setup if the stable helper is absent; and document the one-time bootstrap needed when an older updater cannot emit the new command.

- [x] **Step 4: Run focused tests, full core suite, and static checks**

Run: `pytest tests/test_privilege_policy.py tests/test_repair_release_venv.py tests/test_launch_web_recovery.py -q`
Expected: all focused recovery and installer tests pass.

Run: `pytest --ignore=tests/ui -q`
Expected: core suite passes; report skips explicitly. The project-wide `pytest -q` run also collects browser UI tests; if no external UI server is running, report that separately rather than counting those tests as core coverage.

Run: `pytest tests/ui/test_upload_security.py::TestUploadSecurityUI::test_upload_form_accepts_knxproj -q -s -o addopts=`
Expected: the test's isolated Flask fixture starts its own server and the upload is accepted.

Run: `black --check . && isort --check-only . && flake8 . && bash -n update.sh uninstall.sh installer/setup.sh installer/launch_update.sh installer/repair_release_venv.sh && git diff --check`
Expected: no formatting, lint, shell syntax, or whitespace errors.

- [x] **Step 5: Commit**

Use commit message: `fix: bootstrap active release recovery during setup`.
