# Early CLI Update Guard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reject CLI updates of transactional installations before release lookup or package/system changes.

**Architecture:** `main()` checks for `INSTALL_MODE=update` and an `INSTALL_DIR/current` symlink immediately after `select_install_mode()`. Legacy update behavior remains unchanged. A full-installer test proves that neither release lookup (`curl`) nor dependency installation (`sudo`) occurs.

**Tech Stack:** Bash installer, pytest, GitHub REST API.

**Spec:** `docs/superpowers/specs/2026-11-04-issue-71-early-cli-update-guard-design.md`

## Global Constraints

- Reject before release lookup, privilege/OS checks, or dependency installation.
- Preserve legacy Git-checkout CLI updates and all other installer modes.
- Do not add transactional release activation to the CLI updater.

## Review Focus

- Transactional `--update` with GitHub unreachable: must exit with Web UI guidance before invoking curl (covered by Task 1).
- Transactional `--update` when sudo would fail or alter packages: must exit before invoking sudo (covered by Task 1).
- Legacy checkout `--update`: must continue through release resolution and update behavior (covered by existing installer/release-selection tests in Task 1).
- Fresh install and repair modes: must not be rejected merely because their directories contain unrelated files or no current symlink (covered by existing installer mode tests in Task 1).
- `--help` and invalid mode handling: must retain their existing early behavior (covered by existing installer mode tests in Task 1).

---

### Task 1: Reject transactional CLI updates before external work

**Files:**
- Modify: `install.sh:main`
- Test: `tests/test_installer_modes.py`
- Update: `docs/superpowers/specs/2026-11-04-issue-71-early-cli-update-guard-design.md`

**Interfaces:**
- Consumes: existing `INSTALL_MODE`, `INSTALL_DIR`, `log_error()`, and `select_install_mode()`.
- Produces: an early nonzero exit with explicit Web UI guidance when update mode has a `current` symlink.

- [x] **Step 1: Write the failing test** named `test_transactional_update_is_rejected_before_network_or_sudo`; create an existing Git checkout with `current` pointing into `releases/`, install fake `curl` and `sudo` sentinels, and assert a nonzero exit, Web UI guidance, and neither sentinel ran.
- [x] **Step 2: Run the test to verify it fails** with the current installer reaching external work instead of rejecting the mode.
- [x] **Step 3: Add the minimal guard** in `main()` immediately after `select_install_mode()`; only reject when `INSTALL_MODE` is `update` and `$INSTALL_DIR/current` is a symlink.
- [x] **Step 4: Run the focused and full core suites**: `pytest -q tests/test_installer_modes.py tests/test_release_selection.py`, then `pytest -q -m 'not ui' --ignore=tests/ui`; also run `bash -n install.sh`, Black/isort/flake8/mypy, and `git diff --check`.
- [ ] **Step 5: Commit and push** the fix to `codex/issue-31-lifecycle`; reply to the unresolved GitHub review thread, resolve it after verification, and request a fresh `@codex review`.
- [ ] **Step 6: Verify GitHub** reports all checks successful, the new review covers the pushed head, and no review threads remain unresolved before merging PR #71 into its existing base branch.
