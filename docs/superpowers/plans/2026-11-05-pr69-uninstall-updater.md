# PR #69 Uninstall Updater Coordination Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent uninstall from deleting application files while the oneshot updater is still activating or changing release pointers.

**Architecture:** Inspect the updater unit's actual systemd `ActiveState`, stop it when active or activating, and wait for it to reach an inactive terminal state before disabling units or removing files. Keep already-absent units idempotent and fail safely on unknown systemd states.

**Tech Stack:** Bash, systemd, pytest shell fixtures.

**Spec:** `docs/superpowers/specs/2026-11-05-pr69-review-followups-design.md`

## Global Constraints

- Do not remove application or unit files until the updater is stopped.
- Tolerate an absent or genuinely inactive updater unit; abort before file removal on an unknown state or failed stop.
- Preserve existing uninstall confirmation and user-data retention behavior.

## Review Focus

- A `Type=oneshot` updater in `activating` must be stopped before application deletion (`test_uninstall_stops_updater_while_oneshot_unit_is_activating`).
- An inactive or not-installed updater must still permit idempotent uninstall (`test_normal_uninstall_removes_app_but_preserves_user_data`, `test_purge_removes_custom_paths_and_service_account_and_can_repeat`).
- A stop failure must continue to prevent deletion (`test_failed_service_stop_prevents_file_removal`).
- An unknown systemd state must abort safely before any managed file removal (add an unknown-state assertion to the new test or a focused companion test).

---

### Task 1: Stop and wait for the updater while activating

**Files:**
- Modify: `uninstall.sh`
- Test: `tests/test_uninstall_modes.py`

**Interfaces:**
- Extend the test fixture's fake `systemctl` to return `ActiveState` values for `show`, including `activating`, and record operation order.
- In `uninstall.sh`, stop `knxohui-update.service` when its state is `active`, `activating`, or `deactivating`; wait until it is inactive/dead before proceeding.

- [x] **Step 1: Write the failing activating-state test**

Add `test_uninstall_stops_updater_while_oneshot_unit_is_activating`. Make the fake systemd report `activating`; assert the updater receives `stop` and that this call completes before the application tree's `rm -rf` operation.

- [x] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_uninstall_modes.py::test_uninstall_stops_updater_while_oneshot_unit_is_activating -q`
Expected: FAIL because the current script treats `is-active` status 3 as safe and proceeds without stopping the activating oneshot.

- [x] **Step 3: Add active-state inspection and synchronous stop handling**

Handle active/activating/deactivating states, wait for completion, tolerate only documented absent/inactive states, and abort on unknown state or stop failure. Do not use a nonblocking stop.

- [x] **Step 4: Run uninstaller tests**

Run: `pytest tests/test_uninstall_modes.py -q`
Expected: all uninstall modes, idempotence, confirmation, stop-failure, and new activation tests pass.

- [x] **Step 5: Commit the updater coordination change**

Use commit message: `fix: stop activating updater before uninstall`.
