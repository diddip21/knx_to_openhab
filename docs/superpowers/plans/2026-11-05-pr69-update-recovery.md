# PR #69 Update Recovery Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ensure transactional update recovery uses the active release and persists a rollback target accepted by startup recovery.

**Architecture:** Keep the existing stable install root and release symlink layout. Use `$APP_DIR` for installer recovery commands, and normalize every validated release rollback target to an install-relative `releases/...` path before writing its marker.

**Tech Stack:** Bash, existing Python/pytest shell-integration fixtures.

**Spec:** `docs/superpowers/specs/2026-11-05-pr69-review-followups-design.md`

## Global Constraints

- Preserve legacy installs by retaining `$APP_DIR=$INSTALL_DIR` when there is no transactional `current` link.
- Persist release rollback targets only as validated install-relative `releases/...` paths; retain `legacy` for legacy rollback.
- Do not change update activation, health-check, or rollback policy beyond these findings.

## Review Focus

- Recovery instructions on a transactional install must point into the active release (`test_web_updater_recovery_instructions_use_active_app_dir`).
- An absolute `current` symlink into `releases/` must produce a relative marker accepted by recovery (`test_transactional_update_rolls_back_or_prunes_releases_after_health_check[*-absolute-current-link]`).
- Existing relative-link, legacy rollback, and unsafe-marker cases must remain covered (`tests/test_launch_web_recovery.py`, `test_transactional_update_rolls_back_or_prunes_releases_after_health_check`).

---

### Task 1: Use the active release in recovery instructions

**Files:**
- Modify: `update.sh`
- Test: `tests/test_privilege_policy.py`

**Interfaces:**
- `$APP_DIR` is already resolved before sudoers and credential preflight checks; use it for `installer/migrate_sudoers.sh` and `installer/setup.sh` commands.
- On legacy installs `$APP_DIR` remains `$INSTALL_DIR`, preserving current guidance.

- [x] **Step 1: Write the failing recovery-path test**

Add `test_web_updater_recovery_instructions_use_active_app_dir`. Assert the relevant repair commands use `"$APP_DIR/installer/..."` and do not direct a transactional installation to `"$INSTALL_DIR/installer/..."`.

- [x] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_privilege_policy.py::test_web_updater_recovery_instructions_use_active_app_dir -q`
Expected: FAIL because the current messages reference `$INSTALL_DIR`.

- [x] **Step 3: Update the recovery command paths in `update.sh`**

Use `$APP_DIR` for the installer helper paths in the affected sudoers and setup recovery messages; leave stable-root paths such as `$INSTALL_DIR/current` unchanged. Update the existing credential-preflight assertion in `test_web_updater_checks_external_credentials_before_backup_or_release_changes` to expect `$APP_DIR` as well.

- [x] **Step 4: Run focused path tests**

Run: `pytest tests/test_privilege_policy.py -q`
Expected: all privilege and updater preflight tests pass.

- [x] **Step 5: Commit the recovery-path change**

Use commit message: `fix: use active release in updater recovery guidance`.

### Task 2: Normalize the saved release rollback target

**Files:**
- Modify: `update.sh`
- Test: `tests/test_privilege_policy.py`
- Reference: `installer/launch_web.sh`

**Interfaces:**
- Before writing `RELEASE_RECOVERY_TARGET`, convert the validated resolved previous release directory to the corresponding relative `releases/...` target.
- Continue writing `legacy` when no prior transactional release exists.

- [x] **Step 1: Add a failing interrupted-update integration case**

Add an `absolute-current-link` case to the existing transactional updater integration matrix. Start with `current` as an absolute symlink into `releases/`, interrupt after candidate activation, and assert the candidate marker is exactly a relative `releases/...` target and retry recovery restores the previous release.

- [x] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_privilege_policy.py -k absolute-current-link -q`
Expected: FAIL because `readlink` text is currently persisted unchanged.

- [x] **Step 3: Normalize the validated previous target before marker persistence**

Derive the relative path from the already-resolved release directory after confirming it remains under `$RELEASES_DIR`; do not persist the original symlink text.

- [x] **Step 4: Run recovery tests**

Run: `pytest tests/test_privilege_policy.py tests/test_launch_web_recovery.py -q`
Expected: all rollback, startup recovery, and unsafe-marker tests pass.

- [x] **Step 5: Commit the rollback-target change**

Use commit message: `fix: normalize release rollback targets`.
