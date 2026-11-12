# PR #69 Review Follow-Ups Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resolve the six open PR #69 findings with tested purge, active-release, and backup-retention behavior.

**Architecture:** Keep fixes at their current ownership boundaries: uninstaller validates and removes only managed state; installer/UI recovery use the active transactional release; backup creator filters only application files; backup-cleanup launcher contends on the existing updater lock.

**Tech Stack:** Bash, Python 3.12+, pytest, systemd-compatible `flock`.

**Spec:** `docs/superpowers/specs/2026-11-12-pr69-review-followups-design.md`

## Global Constraints

- Do not relax maintenance-lock/path trust validation or use recursive deletion for a custom lock directory.
- Preserve legacy non-transactional install and recovery behavior.
- Delete an external paths registry only if it is validated as installer-managed and is not already covered by a purge target.
- The updater and cleanup must use the same `KNXOH_DATA_DIR/updater.lock` file and exclusive lock mode.
- Keep application-only archive exclusions; external config/runtime roots must remain complete.

## Review Focus

- A custom lock parent containing unexpected files must prevent account/group deletion before destructive purge begins.
- A caller-selected arbitrary file must never become a privileged purge target merely because it is named `KNXOH_PATHS_FILE`.
- An unmarked legacy paths registry is trusted only at the established default location; a custom registry needs the installer-managed header.
- Transactional links outside `releases/`, broken links, or missing active setup scripts must fail closed rather than run legacy setup.
- Legacy installs without `current` must continue to run setup from `INSTALL_DIR`, including trailing-slash paths and symlinked ancestors.
- External `.git`, `venv`, `.venv`, `__pycache__`, and `.pyc` data must survive a backup; application copies stay excluded.
- Cleanup encountering an active updater must leave backups untouched and return a retryable failure.

---

### Task 1: Safely purge custom maintenance-lock state

**Files:**
- Modify: `uninstall.sh`
- Test: `tests/test_uninstall_modes.py`

**Interfaces:**
- Consumes `KNXOH_MAINTENANCE_LOCK_FILE`, `PURGE`, and the already validated lock directory from `maintenance_lock.sh`.
- Produces a purge preflight that permits only the lock file in a custom lock directory, then unlinks that file and removes the now-empty directory before deleting the service group.

- [x] Add regression tests proving custom lock file and parent are removed before `groupdel`, exact entry-name checks are used for glob-like basenames, and unmanaged sibling entries stop purge before app removal.
- [x] Add a regression test proving unexpected custom-lock-parent contents abort before application removal or `groupdel`.
- [x] Run `./.venv/bin/pytest -q tests/test_uninstall_modes.py` and verify both tests fail before implementation and pass after.

### Task 2: Remove a validated external registry during purge

**Files:**
- Modify: `uninstall.sh`
- Test: `tests/test_uninstall_modes.py`

**Interfaces:**
- Consumes parsed `PATHS_FILE`, `INSTALL_DIR`, `CONFIG_DIR`, `DATA_DIR`, and `BACKUP_DIR`.
- Produces safe purge cleanup for a managed registry outside all removed trees, without separately targeting a registry already removed as part of a tree.

- [x] Add regression cases for a valid custom external registry, registry within a purge tree, an unrelated/untrusted file, and malformed content even when the managed header is present.
- [x] Ensure the fixture registry uses the installer-managed marker and root-safe metadata expected in production.
- [x] Validate the registry's regular-file status, owner/mode, protected parent chain, and managed/recognized-legacy content before any privileged removal.
- [x] Run `./.venv/bin/pytest -q tests/test_uninstall_modes.py` and verify the purge safety assertions.

### Task 3: Use the active release for CLI repair

**Files:**
- Modify: `install.sh`
- Test: `tests/test_installer_lifecycle.py`

**Interfaces:**
- Consumes stable `INSTALL_DIR` and optional `INSTALL_DIR/current` transactional symlink.
- Produces `SETUP_APP_DIR`, selecting `INSTALL_DIR` for legacy installs or the validated resolved `releases/*` target for transactional `--repair`; rejects symlinked setup parents/files and ensures setup and its endpoint helper run from the selected source.

- [x] Extend the lifecycle harness with a transactional installation whose stable root setup is stale and current release setup writes a distinct marker.
- [x] Assert `--repair` runs only current release setup as cwd, makes no fetch/clone request, does not require chmod/write access to the service-owned release, and rejects outside or symlinked setup targets before running code.
- [x] Keep existing clean/repeat/legacy-repair lifecycle coverage passing.
- [x] Run `./.venv/bin/pytest -q tests/test_installer_lifecycle.py tests/test_installer_modes.py`.

### Task 4: Use active release in credential recovery instructions

**Files:**
- Modify: `web_ui/backend/app.py`
- Test: `tests/test_password_auth.py`

**Interfaces:**
- Consumes the running app module path and stable `project_root`.
- Produces a shell-quoted interactive setup command from the verified active release, uses the legacy root only when the running app is genuinely legacy, and fails closed if the transactional source is unsafe.

- [x] Test the 409 credential-migration response under `current -> releases/<tag>`, quote paths containing spaces, and assert missing or symlinked active setup paths do not fall back to stale root setup.
- [x] Preserve the legacy-root path test/behavior when no transactional release path is present.
- [x] Add a Playwright check for the recovery instruction and commit screenshot `docs/screenshots/pr69-active-release-credential-recovery.png`.
- [x] Run `./.venv/bin/pytest -q tests/test_password_auth.py`.

### Task 5: Restrict archive exclusions to the application snapshot

**Files:**
- Modify: `installer/create_update_backup.py`
- Test: `tests/test_update_backup.py`

**Interfaces:**
- Consumes the labeled snapshot roots assembled by `create_update_backup()`.
- Produces full archives for external configuration/runtime roots and applies `_archive_filter` only to the `application` root.

- [x] Add external config/runtime fixtures containing `.git`, `venv`, `.venv`, `__pycache__`, and `.pyc` sentinel files; assert all are archived.
- [x] Retain assertions that equivalent application-tree artifacts remain excluded.
- [x] Run `./.venv/bin/pytest -q tests/test_update_backup.py`.

### Task 6: Serialize scheduled cleanup with updates

**Files:**
- Modify: `installer/launch_backup_cleanup.sh`
- Test: `tests/test_setup_updater_quiescing.py`

**Interfaces:**
- Consumes `KNXOH_DATA_DIR` from the systemd paths environment and the existing `updater.lock` protocol used by `update.sh`.
- Produces a launcher that retains the shared maintenance lock and fails closed without running cleanup when it cannot non-blockingly acquire the updater lock exclusively.

- [x] Add a behavioral test holding `updater.lock` while invoking the cleanup launcher; assert cleanup does not start, then release the lock and assert cleanup starts.
- [x] Use the same update-lock file path and regular-file/symlink guards as `update.sh`.
- [x] Run `./.venv/bin/pytest -q tests/test_setup_updater_quiescing.py`.

### Task 7: Verify, review, and update PR dispositions

- [x] Run all six focused test files (`151 passed`), the full core suite (`997 passed, 13 skipped`), and the UI suite (`208 passed, 2 skipped`).
- [x] Run Black, isort, Flake8, mypy, `bash -n` for changed shell scripts, and `git diff --check` after final code changes.
- [ ] Commit the fixes, request Codex review on the updated PR head, and inspect every new review finding before proceeding.
- [ ] Reply with tested dispositions for the six open review threads; resolve only findings actually addressed.
- [ ] Recheck all GitHub checks and PR review threads. Do not merge until all checks are green and no valid review finding is left unresolved.
