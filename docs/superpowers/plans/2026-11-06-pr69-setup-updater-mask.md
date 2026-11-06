# Setup Updater Runtime-Mask Follow-Up Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent a finishing or newly queued updater from overlapping setup after the updater itself restarts the Web UI.

**Architecture:** Source small mask/unmask functions into setup. Runtime-mask only an unmasked, installed updater unit, quiesce it, stop the Web UI again, and verify quiescence before mutations. Keep the mask through setup and release only the mask setup owns, including from the failure trap.

**Tech Stack:** Bash, systemd, pytest subprocess tests.

**Spec:** `docs/superpowers/specs/2026-11-06-pr69-setup-updater-mask-design.md`

## Global Constraints

- Do not alter persistent enablement, add sudoers authority, or change the updater lock contract.
- Do not interrupt an active transactional update.
- Preserve missing-unit and already-masked unit behavior.
- Restore an owned runtime mask on both setup success and failure.

## Review Focus

- Existing persistent/runtime masks are not removed by setup — test the mask helper with `LoadState=masked`.
- Missing units remain compatible — test `LoadState=not-found`.
- The updater's own Web UI restart is followed by another Web UI stop and an idle/job recheck — assert setup ordering.
- Masking spans all setup mutations and is removed after service restart or before failure restoration — assert both ordering paths.
- Systemd mask/unmask failures fail safely and preserve mask ownership state — simulate command failures.

---

### Task 1: Hold a runtime updater mask through setup

**Files:**
- Create: `installer/setup_update_service_mask.sh`
- Modify: `installer/setup.sh`
- Modify: `tests/test_setup_updater_quiescing.py`
- Modify: `docs/PRODUCTION_GUIDE.md`

**Interfaces:**
- `mask_update_service_for_setup()` sets `KNXOH_UPDATE_SERVICE_RUNTIME_MASKED=1` only after setup successfully creates a runtime mask.
- `unmask_update_service_after_setup()` removes only that setup-owned runtime mask and clears the flag on success.
- Setup masks before updater quiescence, stops the Web UI again after the updater finishes, runs the final quiescence check, then mutates files. The EXIT trap unsets an owned runtime mask before restoring prior services.

- [x] **Step 1: Add mask-ownership and setup-order regressions**

Use fake `sudo systemctl` for loaded, not-found, already-masked, mask-failure, and unmask-failure cases. Assert setup's sequence is initial Web UI stop → runtime mask → wait/quiesce → second Web UI stop → final quiesce → first mutation; assert the mask remains through the service restart and cleanup precedes failure restoration.

- [x] **Step 2: Run the new regressions and verify they fail**

Run: `pytest tests/test_setup_updater_quiescing.py -q`

Expected: FAIL because setup does not own a runtime mask or perform the second stop/final check.

- [x] **Step 3: Add setup-owned runtime masking and close the restart window**

Source the mask helper, preserve already-masked/not-found units, runtime-mask before waiting, stop the Web UI again after quiescence, run the final check, and unmask after successful setup or in the EXIT trap before restoring services. Update production guidance.

- [x] **Step 4: Run focused setup and installer tests**

Run: `pytest tests/test_setup_updater_quiescing.py tests/test_privilege_policy.py tests/test_installer_guardrails.py tests/integration/test_installer.py -q`

Expected: all tests pass.

- [x] **Step 5: Verify and commit**

Run: `black --check tests/test_setup_updater_quiescing.py && isort --check-only tests/test_setup_updater_quiescing.py && flake8 tests/test_setup_updater_quiescing.py && bash -n installer/setup.sh installer/setup_update_service_mask.sh installer/quiesce_update_service.sh && git diff --check`

Commit: `fix: mask updater while setup mutates files`.
