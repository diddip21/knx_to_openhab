# PR #69 Uninstall Updater Coordination Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent uninstall from deleting application files while the oneshot updater is still activating or changing release pointers.

**Architecture:** Inspect the updater unit's actual systemd `ActiveState`, stop it when active or activating, and wait for it to reach an inactive terminal state before disabling units or removing files. Keep already-absent units idempotent and fail safely on unknown systemd states.

**Tech Stack:** Bash, systemd, pytest shell fixtures.

**Spec:** `docs/superpowers/specs/2026-11-05-pr69-review-followups-design.md`

## Global Constraints

- Do not remove application or unit files until the updater is stopped.
- Stop the Web UI before checking/stopping the updater so no new update request can start during teardown.
- Tolerate an absent or genuinely inactive updater unit; abort before file removal on an unknown state or failed stop.
- Preserve existing uninstall confirmation and user-data retention behavior.

## Review Focus

- A `Type=oneshot` updater in `activating` must be stopped before application deletion (`test_uninstall_stops_updater_while_oneshot_unit_is_activating`).
- A Web UI that starts an updater while shutting down must be quiesced before the final updater check (`test_uninstall_quiesces_web_service_before_final_updater_stop`).
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
- In `uninstall.sh`, stop `knxohui.service` before `knxohui-update.service`; stop the updater when its state is `active`, `activating`, or `deactivating`, and wait until it is inactive/dead before proceeding.

- [x] **Step 1: Write the failing activating-state test**

Add `test_uninstall_stops_updater_while_oneshot_unit_is_activating` and `test_uninstall_quiesces_web_service_before_final_updater_stop`. Make fake systemd report an activating updater and simulate a Web UI-triggered start during Web UI shutdown; assert the Web UI is stopped first, the updater receives its final `stop`, and both happen before the application tree's `rm -rf` operation.

- [x] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_uninstall_modes.py::test_uninstall_stops_updater_while_oneshot_unit_is_activating -q`
Expected: FAIL on the earlier implementation because it treated an activating oneshot as inactive; the review follow-up race test also shows that checking the updater before stopping the Web UI can miss a new start.

- [x] **Step 3: Add active-state inspection and synchronous stop handling**

Stop the Web UI before the updater. Handle active/activating/deactivating states, wait for completion, tolerate only documented absent/inactive states, and abort on unknown state or stop failure. Do not use a nonblocking stop.

- [x] **Step 4: Run uninstaller tests**

Run: `pytest tests/test_uninstall_modes.py -q`
Expected: all uninstall modes, idempotence, confirmation, stop-failure, and new activation tests pass.

- [x] **Step 5: Commit the updater coordination change**

Use commit message: `fix: stop activating updater before uninstall`.
