# PR #70 Interrupted-Release Boot Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore a known-good release before the Web UI launches when a reboot leaves `current` pointing at a release that still has `.update-in-progress`.

**Architecture:** Add recovery to the stable `installer/launch_web.sh` launcher. It uses the same `updater.lock` as `update.sh`: if the lock is busy, an active update owns validation and the launcher leaves `current` alone; if the lock is free, it validates the saved rollback target and atomically restores it before selecting the app to launch. Add a capability marker and updater preflight check so the updated root-installed launcher is installed through the existing setup flow before another Web UI update can begin.

**Tech Stack:** Bash, systemd-installed launcher, Python 3.12+ Flask updater, pytest; no new dependencies.

**Spec:** `docs/superpowers/specs/2026-11-05-pr70-review-followup-design.md`

## Global Constraints

- Do not add a systemd unit or dependency.
- A busy `updater.lock` means a real update may be validating the candidate; never roll it back from the launcher in that state.
- Only restore a regular `.update-in-progress` marker whose rollback target is valid and within the install tree, or the literal `legacy` target.
- Use a temporary symlink and atomic rename for release-pointer restoration; for `legacy`, remove `current` only after confirming the legacy app is runnable.
- Preserve files and fail closed with an actionable error on malformed marker, unsafe/missing target, or lock-path failure.
- The setup-installed stable launcher must advertise `KNXOH_BOOT_RECOVERY_VERSION=1`; updater preflight blocks queueing and displays the existing `setup.sh` instruction if this capability is absent.
- No merge; keep PR #70 open.

## Review Focus

- No marker leaves `current` unchanged and launches the selected release (`test_launcher_does_not_change_current_without_marker`).
- A stale marker restores a valid saved release before launching Gunicorn (`test_launcher_restores_previous_release_with_stale_marker`).
- A `legacy` marker removes `current` only when the legacy launcher is runnable (`test_launcher_restores_legacy_install_with_stale_marker`).
- A held `updater.lock` leaves the candidate selected so active health validation can continue (`test_launcher_does_not_rollback_while_update_lock_is_held`).
- Malformed markers and rollback paths outside `INSTALL_DIR` fail closed and preserve the marker/current pointer (`test_launcher_rejects_unsafe_rollback_target`).

---

### Task 1: Recover stale release markers in the stable launcher

**Files:**
- Modify: `installer/launch_web.sh`
- Test: `tests/test_launch_web_recovery.py`

**Interfaces:**
- Consumes: `KNXOH_INSTALL_DIR`, `KNXOH_DATA_DIR`, `$INSTALL_DIR/current`, `$KNXOH_DATA_DIR/updater.lock`, and the existing `.update-in-progress` marker format (`legacy` or a prior symlink target).
- Produces: launcher recovery before `APP_DIR` selection; marker sentinel `KNXOH_BOOT_RECOVERY_VERSION=1` for setup readiness checks.

- [x] **Step 1: Add failing launcher tests**

Create temporary install trees with fake `venv/bin/gunicorn` launchers. Cover all five Review Focus cases, asserting both the selected `current` target and which fake launcher ran. Use a real `flock` holder for the in-progress case.

- [x] **Step 2: Run launcher tests and verify failure**

Run: `python -m pytest -q tests/test_launch_web_recovery.py`

Expected: stale markers currently remain selected and the candidate launcher runs; no-marker and held-lock baseline cases establish the expected non-regression behavior.

- [x] **Step 3: Implement recovery before app selection**

In `installer/launch_web.sh`, require the absolute configured data directory, reject a symlink/non-regular `updater.lock`, and open that lock. Acquire it nonblocking; if unavailable, close the descriptor and leave `current` unchanged. If acquired, inspect the resolved current release's regular marker. For `legacy`, require a runnable legacy venv before removing `current`. For a saved release target, resolve relative targets from `INSTALL_DIR`, require the resolved directory to be under `INSTALL_DIR/releases/` and runnable, then restore with a temporary symlink and `mv -Tf`. Preserve invalid state and exit nonzero with an actionable message. Release and close the lock before the existing launcher selection. Add the capability sentinel to the stable script.

- [x] **Step 4: Run launcher tests and verify they pass**

Run: `python -m pytest -q tests/test_launch_web_recovery.py`

Expected: all stale-marker, legacy, no-marker, active-lock, and unsafe-target cases pass.

- [x] **Step 5: Commit**

```bash
git add installer/launch_web.sh tests/test_launch_web_recovery.py
git commit -m "fix: recover interrupted release before Web UI launch"
```

### Task 2: Gate updates on the installed recovery launcher

**Files:**
- Modify: `web_ui/backend/updater.py`
- Test: `tests/test_updater.py`

**Interfaces:**
- Consumes: `installer/launch_web.sh` capability sentinel `KNXOH_BOOT_RECOVERY_VERSION=1` installed at `/usr/local/libexec/knx_to_openhab/launch_web.sh`.
- Produces: `_update_worker_setup_error()` returns the existing setup instruction when the stable launcher is missing the recovery capability.

- [x] **Step 1: Add a failing readiness test**

Extend `test_update_worker_readiness_requires_installed_files_and_sudo_permission` with the installed web launcher. Verify readiness is rejected when the launcher is missing the sentinel and accepted when the sentinel is present and existing service prerequisites pass.

- [x] **Step 2: Run the readiness test and verify failure**

Run: `python -m pytest -q tests/test_updater.py::test_update_worker_readiness_requires_installed_files_and_sudo_permission`

Expected: the old launcher currently passes readiness because it is not checked.

- [x] **Step 3: Gate readiness on the launcher capability**

Add a path constant for `/usr/local/libexec/knx_to_openhab/launch_web.sh`. In `_update_worker_setup_error()`, require that the file is readable and contains the exact sentinel; otherwise return `_update_worker_setup_instruction()` before any request is published.

- [x] **Step 4: Run updater and launcher regressions**

Run: `python -m pytest -q tests/test_updater.py tests/test_launch_web_recovery.py`

Expected: all tests pass, including `test_trigger_update_requires_worker_setup_before_queuing`.

- [x] **Step 5: Commit**

```bash
git add web_ui/backend/updater.py tests/test_updater.py
git commit -m "fix: require boot recovery launcher before updates"
```
