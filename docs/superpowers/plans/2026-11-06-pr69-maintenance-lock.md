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
- A runtime environment specifies a different maintenance lock from `paths.env` → reject before acquiring any lock or mutating files.
- No lock is persisted yet and a runtime tool specifies a custom path → reject; only setup's initial-install flow may accept it.
- A valid persisted custom path contains spaces or shell metacharacters → parse it as data and use that exact path without evaluation.

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

- [x] **Step 5: Commit** (`f3a19fc`)

### Task 4: Protect uninstall and preserve administrator masks

**Files:**
- Modify: `uninstall.sh`
- Modify: `installer/setup.sh`
- Create: `installer/uninstall_unit_files.sh`
- Create: `installer/knx_to_openhab-lock.conf`
- Modify: `tests/test_uninstall_modes.py`
- Modify: `tests/test_maintenance_lock.py`
- Modify: `docs/PRODUCTION_GUIDE.md`

**Interfaces:**
- Consumes: Task 1 lock helper and Task 3 generic quiescence helper.
- Produces: uninstall holds exclusive maintenance ownership through disable/removal, re-stops the Web UI after updater shutdown, rechecks state/jobs before deletion, and retains administrator-owned mask symlinks.

- [x] **Step 1: Add race, lock, not-found, and mask-preservation regressions**

Cover updater-triggered Web UI restart, queued starts after the initial stop, a not-found updater with retained activity, uninstall under lock contention, and persistent mask symlinks in each managed unit location.

- [x] **Step 2: Run new uninstall tests and verify current behavior fails**

Run: `pytest tests/test_uninstall_modes.py -q`.

Expected: failures show UI restart/mask-removal races.

- [x] **Step 3: Implement uninstall coordination and mask preservation**

Stop and quiesce services, retry until exclusive maintenance ownership is held, perform a final state/job check, then disable/remove files. Do not remove `/dev/null` unit-mask symlinks owned by the administrator.

- [x] **Step 4: Run uninstall and full maintenance-focused suites**

Run: `pytest tests/test_uninstall_modes.py tests/test_setup_updater_quiescing.py tests/test_maintenance_lock.py -q`; `bash -n uninstall.sh`.

Expected: all tests pass and Bash syntax succeeds.

- [x] **Step 5: Commit** (`acf9252`)

### Task 5: Full verification and fresh review

- [x] Run the full core suite, formatting/lint checks, relevant integration tests, Bash syntax checks, and `git diff --check`.
- [x] Generate the full diff from the previous review base and request a fresh read-only review.
- [x] Resolve Important findings with regression-first follow-ups; document any Minor disposition. Do not push or merge.

### Task 6: Fence legacy updater-lock holders

**Files:**
- Create: `installer/hold_updater_locks.sh` — acquire multiple exclusive updater locks in one holder process and report a readiness marker.
- Modify: `installer/setup.sh`, `installer/setup_maintenance.sh`, `installer/repair_release_venv.sh`, `uninstall.sh`.
- Modify: `tests/test_setup_updater_quiescing.py`, `tests/test_repair_release_venv.py`, `tests/test_uninstall_modes.py`.
- Modify: this design/plan and `.superpowers/sdd/2026-11-06-pr69-maintenance-lock/progress.md`.

**Interfaces:**
- Setup consumes the previously saved and selected `DATA_DIR` values and holds their distinct `updater.lock` files in addition to the exclusive maintenance lock.
- Uninstall consumes the configured `DATA_DIR/updater.lock` in addition to the maintenance lock.
- Setup recovery consumes `KNXOH_SETUP_UPDATER_LOCK_HELD=1` only when the setup parent retains the lock holder; standalone recovery keeps its current nonblocking acquisition behavior.

- [x] **Step 1: Add regressions for lock-holder contention, setup path migration, uninstall fencing, and repair inheritance**

Verify a real updater-lock holder returns a distinct contention status for an already-held lock, Setup requests both persisted and selected `DATA_DIR` locks before the first app mutation, Uninstall holds the configured updater lock before removing files, and setup recovery skips only the duplicate updater-lock acquisition when the parent explicitly holds it.

- [x] **Step 2: Run the regressions and verify they fail before implementation**

Run focused tests in `tests/test_setup_updater_quiescing.py`, `tests/test_uninstall_modes.py`, and `tests/test_repair_release_venv.py`.

Expected: missing lock-holder integration or setup inheritance assertions fail.

- [x] **Step 3: Implement reusable updater-lock holder and integrate setup/uninstall**

Create `installer/hold_updater_locks.sh`; run it as the service account with a readiness marker, hold distinct saved/selected updater locks throughout setup mutations, and hold the configured updater lock through uninstall mutations. Preserve standalone recovery's existing nonblocking lock acquisition; bypass it only for setup's explicit `KNXOH_SETUP_UPDATER_LOCK_HELD=1` context.

- [x] **Step 4: Run focused setup, uninstall, repair, and lock suites**

Run: `pytest tests/test_setup_updater_quiescing.py tests/test_uninstall_modes.py tests/test_repair_release_venv.py tests/test_maintenance_lock.py -q`.

Expected: all focused tests pass and Bash syntax succeeds.

- [x] **Step 5: Run full core suite, lint, syntax, and diff checks**

Run: `pytest --ignore=tests/ui -q`, Black, isort, Flake8, Bash syntax checks, and `git diff --check`.

Expected: all applicable checks pass.

### Task 7: Reject untrusted maintenance-lock ancestors

**Files:**
- Modify: `installer/maintenance_lock.sh`, `installer/write_maintenance_lock_tmpfiles.py`.
- Modify: `tests/test_maintenance_lock.py`, `tests/test_launch_web_recovery.py`, `tests/test_repair_release_venv.py`, `tests/test_update_backup.py`, `tests/test_setup_updater_quiescing.py`, `tests/test_privilege_policy.py`.
- Modify: this design/plan and `.superpowers/sdd/2026-11-06-pr69-maintenance-lock/progress.md`.

- [x] Add RED regressions proving validation, runtime acquisition, and tmpfiles generation reject a private lock directory beneath an untrusted writable ancestor.
- [x] Apply the same trust check to every existing ancestor during validation, tmpfiles generation, and runtime lock acquisition; allow only root-owned sticky writable ancestors.
- [x] Isolate unrelated temporary-path lock tests with test-only validator overrides and run affected suites as root and an unprivileged user.
- [x] Run full core tests, lint, syntax, and diff checks after all review follow-ups.

### Task 8: Resolve one persisted maintenance-lock path at runtime

**Files:**
- Modify: `installer/maintenance_lock.sh`, `installer/setup.sh`, `installer/setup_maintenance.sh`, `installer/repair_release_venv.sh`, `update.sh`, `uninstall.sh`.
- Modify: `tests/test_maintenance_lock.py`, `tests/test_setup_updater_quiescing.py`, `tests/test_launch_web_recovery.py`, `tests/test_repair_release_venv.py`, `tests/test_update_backup.py`, `tests/test_uninstall_modes.py`, `tests/test_privilege_policy.py`.
- Modify: this design/plan and `.superpowers/sdd/2026-11-06-pr69-maintenance-lock/progress.md`.

**Contract:**
- `resolve_maintenance_lock_path PATHS_FILE [allow-initial]` parses the saved key as data, rejects duplicate/malformed target-key entries or values and conflicting environment overrides, then exports the resolved path.
- Runtime callers use strict mode: persisted path wins, an explicit override must match, and an unpersisted custom override is refused. The default path remains valid before initial setup.
- Setup alone invokes `allow-initial` so an administrator-selected custom path can be used before its first persistence.
- `update.sh` and recovery ignore `KNXOH_MAINTENANCE_LOCK_HELPER`; use the fixed stable helper, falling back only to a fixed package-local helper path. Service launchers inherit strict resolution through `acquire_maintenance_shared_lock()`.

- [x] **Step 1: Add resolver and integration regressions**

Add tests named `test_runtime_lock_path_uses_saved_custom_path_when_environment_is_unset`, `test_runtime_lock_path_rejects_conflicting_override`, `test_runtime_lock_path_rejects_unpersisted_custom_override`, `test_update_ignores_environment_selected_lock_helper`, and script-level checks that update, repair, and uninstall use the same resolved file. Include quoted paths with spaces and duplicate/malformed saved keys.

- [x] **Step 2: Run the new regressions and verify they fail before implementation**

Run the new focused tests in `tests/test_maintenance_lock.py`, `tests/test_update_backup.py`, `tests/test_repair_release_venv.py`, and `tests/test_uninstall_modes.py`.

Expected: recovery selects the default rather than a saved custom path, conflicting update overrides are accepted, and the helper environment override remains effective.

- [x] **Step 3: Implement `resolve_maintenance_lock_path(paths_file, policy)`**

In `installer/maintenance_lock.sh`, parse the persisted key as data with Python `shlex`, reject duplicate/malformed values, compare the captured environment override, select the default or persisted path, and export the result. Strict policy rejects an unpersisted custom path; only `allow-initial` accepts one. Call strict resolution before runtime shared/exclusive acquisition; have setup's maintenance wrapper request `allow-initial` explicitly.

- [x] **Step 4: Integrate the resolver and fixed helper selection**

Have update, repair, and uninstall resolve before lock acquisition. Remove `KNXOH_MAINTENANCE_LOCK_HELPER` selection and use a fixed stable helper path plus fixed package-local fallback. Keep setup's existing saved-path immutability checks and persist an initial custom value before service starts.

- [x] **Step 5: Run the focused integration groups**

Run: `pytest tests/test_maintenance_lock.py tests/test_setup_updater_quiescing.py tests/test_launch_web_recovery.py tests/test_repair_release_venv.py tests/test_update_backup.py tests/test_uninstall_modes.py tests/test_privilege_policy.py -q`.

Expected: all paths agree on one lock inode, strict runtime conflicts fail before side effects, and setup initial custom-path compatibility remains intact.

- [x] **Step 6: Run full core tests, lint, syntax, and diff checks, then request a fresh review**

### Task 9: Close out the remaining review findings

**Files:**
- Modify: `installer/write_maintenance_lock_tmpfiles.py`, `uninstall.sh`.
- Modify: `tests/test_maintenance_lock.py`, `tests/test_setup_unit_masks.py`, `tests/test_setup_updater_quiescing.py`, `tests/test_uninstall_modes.py`.
- Modify: this design/plan and `.superpowers/sdd/2026-11-06-pr69-maintenance-lock/progress.md`.

- [x] Disposition runtime masks with tests proving masked regular unit fragments are not overwritten or started and active masked units are quiesced.
- [x] Add a RED regression showing tmpfiles generation accepts a missing service group when the lock parent is absent; require the group before emitting the rule.
- [x] Add a RED regression that purging a default-lock installation removes its dedicated `/run/lock/knx_to_openhab` directory before deleting the service group, while normal uninstall and custom lock parents remain untouched.
- [x] Remove the default lock parent safely while the exclusive maintenance-lock inode is still held; do not unlink/recreate the lock between unlock and process exit.
- [x] Add a RED regression proving purge fails closed before destructive actions when the default lock parent is a mountpoint; use `mountpoint`'s documented status to fail closed when inspection is unavailable.
- [x] Refuse default-parent mountpoints before disabling units or deleting files; custom parents are not inspected or removed.
- [x] Run focused lock, setup-mask, and uninstall groups (`105 passed`), then full verification (`1171 passed, 15 skipped`) and a fresh read-only review.
