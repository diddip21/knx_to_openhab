# Setup and Uninstall Maintenance Lock Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep service processes and update/recovery work out of the filesystem mutation windows used by setup and uninstall.

**Architecture:** Stable launch helpers acquire a non-blocking shared maintenance lock and retain it through their work. Setup and uninstall stop services, confirm updater quiescence, then hold the same lock exclusively through mutations; the existing updater lock remains unchanged for recovery. A not-found systemd fragment is not considered quiescent until state and jobs are independently confirmed.

**Tech Stack:** Bash, systemd, `flock`, pytest subprocess tests.

**Spec:** `docs/superpowers/specs/2026-11-06-pr69-maintenance-lock-design.md`

## Global Constraints

- Keep the lock stable across application, runtime-data, and custom-path migrations.
- Shared acquisition is non-blocking and fails closed; exclusive acquisition is bounded and fail-closed.
- Do not modify persistent systemd enablement or overwrite administrator-owned masks.
- Keep the updater lock contract unchanged; setup recovery may use its existing lock under the already-held maintenance lock.
- Do not mutate application files before updater quiescence and exclusive maintenance-lock acquisition.

## Review Focus

- Unit start arrives after a quiescence query but before lock acquisition → retry stop/quiesce until exclusive ownership.
- Web UI has an activating state or queued start while setup stops it → inspect state/jobs and wait or fail closed.
- Unit fragment is not-found but an old process/job remains → verify retained state/jobs before proceeding.
- Setup fails after acquiring the lock or while restoring services → release lock before service restoration.
- Existing persistent unit mask is present → preserve the mask rather than replacing/removing it.

---

### Task 1: Add a stable shared/exclusive maintenance-lock helper

**Files:**
- Create: `installer/maintenance_lock.sh`
- Test: `tests/test_maintenance_lock.py`

**Interfaces:**
- Produces: `ensure_maintenance_lock(group)`, `acquire_maintenance_shared_lock()`, `acquire_maintenance_exclusive_lock()`, and `release_maintenance_lock()`.
- Shared and exclusive lock file: `${KNXOH_MAINTENANCE_LOCK_FILE:-/run/lock/knx_to_openhab/maintenance.lock}`.
- Shared lock is non-blocking; exclusive acquisition is non-blocking so callers can retry without hiding systemd races.
- Lock descriptors remain open across `exec` when held by a service launcher.

- [x] **Step 1: Write lock creation, contention, and descriptor-lifetime regressions**

Test that the helper creates a root-owned-directory-compatible regular lock file without truncating an existing inode; one process holding exclusive lock makes shared acquisition fail, and shared holders make exclusive acquisition fail. Verify release clears ownership and that the descriptor remains held across an `exec` child.

- [x] **Step 2: Run the new tests and verify the helper contract is absent**

Run: `pytest tests/test_maintenance_lock.py -q`

Expected: FAIL because the lock helper does not exist.

- [x] **Step 3: Implement the lock helper**

Use `flock -s -n` and `flock -x -n`; distinguish contention from lock-file/command errors. Ensure the setup path creates a root-owned directory and a group-readable/writable regular file without truncating an existing lock inode.

- [x] **Step 4: Run lock regressions and static checks**

Run: `pytest tests/test_maintenance_lock.py -q`; `bash -n installer/maintenance_lock.sh`; `shellcheck installer/maintenance_lock.sh` when available.

Expected: all tests pass; syntax succeeds.

- [x] **Step 5: Commit**

### Task 2: Gate stable service and update/recovery launchers

**Files:**
- Modify: `installer/launch_web.sh`
- Modify: `installer/launch_update.sh`
- Modify: `installer/launch_backup_cleanup.sh`
- Modify: `update.sh`
- Modify: `installer/repair_release_venv.sh`
- Modify: `installer/setup.sh` stable-helper installation
- Test: `tests/test_setup_updater_quiescing.py`, `tests/test_repair_release_venv.py`

**Interfaces:**
- Consumes: Task 1 lock functions.
- Produces: all service entry points take and retain a shared maintenance lock; repair may skip only the shared lock when setup explicitly passes `KNXOH_SETUP_LOCK_HELD=1`.

- [x] **Step 1: Add failing service-start and updater-start contention tests**

Run real launcher/helper scripts with a temporary exclusive lock held. Assert Web UI, update service, backup cleanup, direct `update.sh`, and standalone repair exit before executing application work. Assert setup-authorized repair still relies on the existing updater lock.

- [x] **Step 2: Run focused tests and verify they fail against current launchers**

Run: `pytest tests/test_setup_updater_quiescing.py tests/test_repair_release_venv.py -q`

Expected: new contention cases fail because launchers do not consult the maintenance lock.

- [x] **Step 3: Gate each service entry point with a shared lock**

Source the stable helper before application work, retain the shared descriptor through `exec`, and make contention fail closed. Add setup installation of the helper before installing the launch scripts. Preserve the existing updater-lock behavior in the repair helper.

- [x] **Step 4: Run focused service and recovery tests**

Run: `pytest tests/test_setup_updater_quiescing.py tests/test_repair_release_venv.py tests/test_run_update_request.py -q`.

Expected: all tests pass, including launch attempts during exclusive maintenance.

- [x] **Step 5: Commit**

### Task 3: Make setup acquire and hold exclusive maintenance ownership

**Files:**
- Modify: `installer/setup.sh`
- Modify: `installer/quiesce_update_service.sh`
- Create: `installer/quiesce_systemd_unit.sh`
- Create: `installer/setup_maintenance.sh`
- Create: `installer/install_update_unit.sh`
- Modify: `tests/test_setup_updater_quiescing.py`
- Modify: `docs/PRODUCTION_GUIDE.md`

**Interfaces:**
- Consumes: Task 1 lock helper and Task 2 shared-lock launchers.
- Produces: setup stops services, loops through updater quiescence and exclusive lock acquisition, verifies final service state/jobs before its first application mutation, releases ownership before restarting/restoring services, and preserves a masked updater unit.
- `quiesce_systemd_unit.sh UNIT` exits successfully only for inactive/failed/not-found units with no pending jobs; inspection errors fail closed.
- `setup_maintenance.sh` exports `acquire_setup_maintenance_lock()` and `release_maintenance_lock()` for setup to source.
- `install_update_unit.sh SOURCE DESTINATION` installs only when systemd does not report `LoadState=masked`.

- [x] **Step 1: Add regressions for activating UI, queued starts, not-found active units, masked units, and lock-acquisition races**

Assert setup re-stops and re-quiesces when a shared start wins a lock race; assert an active or queued unit whose fragment is not-found is not accepted; assert pre-existing masks are never replaced; assert EXIT cleanup releases the lock before restoring services.

- [x] **Step 2: Run the new regressions and verify they fail against current setup/quiescence**

Run: `pytest tests/test_setup_updater_quiescing.py -q`.

Expected: failures expose the missing generic state/job inspection and exclusive-lock retry behavior.

- [x] **Step 3: Implement fail-closed unit quiescence and setup lock lifecycle**

Use `systemctl show` and `list-jobs`, cancel queued non-stop jobs, synchronously stop active/activating services, and recheck state/jobs. For updater `LoadState=not-found`, continue to inspect retained `ActiveState` and jobs. Setup repeats stop/quiesce when shared-lock contention occurs; only after the exclusive lock and final checks may it mutate application files. Skip replacing an updater unit that systemd reports masked.

- [x] **Step 4: Run setup, installer, and recovery tests**

Run: `pytest tests/test_setup_updater_quiescing.py tests/test_installer_guardrails.py tests/test_privilege_policy.py tests/integration/test_installer.py -q`; `bash -n installer/setup.sh installer/quiesce_systemd_unit.sh installer/quiesce_update_service.sh`.

Expected: all focused tests pass and Bash syntax checks succeed.

- [ ] **Step 5: Commit**

### Task 4: Protect uninstall and preserve administrator masks

**Files:**
- Modify: `uninstall.sh`
- Modify: `tests/test_uninstall_modes.py`
- Modify: `docs/PRODUCTION_GUIDE.md`

**Interfaces:**
- Consumes: Task 1 lock helper and Task 3 generic quiescence helper.
- Produces: uninstall holds exclusive maintenance ownership through disable/removal, re-stops the Web UI after updater shutdown, rechecks state/jobs before deletion, and retains administrator-owned mask symlinks.

- [ ] **Step 1: Add race, lock, not-found, and mask-preservation regressions**

Cover updater-triggered Web UI restart, queued starts after the initial stop, a not-found updater with retained activity, uninstall under lock contention, and persistent mask symlinks in each managed unit location.

- [ ] **Step 2: Run new uninstall tests and verify current behavior fails**

Run: `pytest tests/test_uninstall_modes.py -q`.

Expected: failures show UI restart/mask-removal races.

- [ ] **Step 3: Implement uninstall coordination and mask preservation**

Stop and quiesce services, retry until exclusive maintenance ownership is held, perform a final state/job check, then disable/remove files. Do not remove `/dev/null` unit-mask symlinks owned by the administrator.

- [ ] **Step 4: Run uninstall and full maintenance-focused suites**

Run: `pytest tests/test_uninstall_modes.py tests/test_setup_updater_quiescing.py tests/test_maintenance_lock.py -q`; `bash -n uninstall.sh`.

Expected: all tests pass and Bash syntax succeeds.

- [ ] **Step 5: Commit**

### Task 5: Full verification and fresh review

- [ ] Run the full core suite, formatting/lint checks, relevant integration tests, Bash syntax checks, and `git diff --check`.
- [ ] Generate the full diff from the previous review base and request a fresh read-only review.
- [ ] Resolve Important findings with regression-first follow-ups; document any Minor disposition. Do not push or merge.
