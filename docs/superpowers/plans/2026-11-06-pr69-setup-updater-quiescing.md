# Setup/Updater Quiescing Follow-Up Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ensure setup does not mutate installation or runtime files while the independent updater is active or queued.

**Architecture:** Add a focused systemd quiescing helper called by setup immediately after stopping the Web UI. It waits for active update work, cancels queued jobs, verifies inactivity, and fails before setup mutations if safety cannot be established.

**Tech Stack:** Bash, systemd `systemctl`, pytest subprocess tests.

**Spec:** `docs/superpowers/specs/2026-11-06-pr69-setup-updater-quiescing.md`

## Global Constraints

- Do not add dependencies or sudoers authority.
- Preserve the existing shared updater lock and setup recovery trap.
- Keep first-install behavior when `knxohui-update.service` is not loaded.
- Do not interrupt an already-running transactional update; wait for it to finish.

## Review Focus

- An active updater is allowed to finish before setup proceeds — simulate active then inactive state.
- Queued start jobs are canceled before setup proceeds — simulate an inactive unit with a queued start.
- Missing units remain compatible with first install — simulate `LoadState=not-found`.
- systemd inspection/cancel errors and unknown states fail closed — assert nonzero exit; the bounded-wait loop must also have a deterministic upper bound.
- The helper is actually wired before mutations — assert Web UI stop precedes helper invocation and helper invocation precedes venv/rsync/runtime mutation.

---

### Task 1: Quiesce the updater before setup mutations

**Files:**
- Create: `installer/quiesce_update_service.sh`
- Modify: `installer/setup.sh`
- Modify: `docs/PRODUCTION_GUIDE.md`
- Test: `tests/test_setup_updater_quiescing.py`

**Interfaces:**
- Consumes: the installed `knxohui-update.service` unit and `systemctl` job/state queries.
- Produces: a zero exit only when the unit is absent or inactive with no pending jobs; otherwise a diagnostic nonzero exit before setup mutates files.

- [x] **Step 1: Add subprocess tests for active, queued, absent, and unsafe updater states**

Use a fake `sudo systemctl` executable and state files; exercise the actual helper script for active-then-inactive, queued-start, absent-unit, and systemctl-error/unknown-state paths. Also assert setup calls the helper after stopping the Web UI and before its first mutation.

- [x] **Step 2: Run the new tests and verify the missing helper/wiring fails**

Run: `pytest tests/test_setup_updater_quiescing.py -q`

Expected: FAIL because the helper and setup call do not yet exist.

- [x] **Step 3: Implement, wire, and document updater quiescing**

Wait up to 15 minutes for active updater state to become inactive; cancel each queued non-stop job by its systemd job ID; recheck until no jobs remain. Handle a missing unit as success and abort on unknown state or systemctl failure. Call it immediately after stopping `knxohui.service` and before account, venv, rsync, migration, or runtime changes. Document the wait/cancel behavior and fail-before-mutation contract in `docs/PRODUCTION_GUIDE.md`.

- [x] **Step 4: Run setup-quiescing and related installer tests**

Run: `pytest tests/test_setup_updater_quiescing.py tests/test_privilege_policy.py tests/test_installer_guardrails.py tests/integration/test_installer.py -q`

Expected: all tests pass.

- [x] **Step 5: Verify and commit**

Run: `black --check tests/test_setup_updater_quiescing.py && isort --check-only tests/test_setup_updater_quiescing.py && flake8 tests/test_setup_updater_quiescing.py && bash -n installer/setup.sh installer/quiesce_update_service.sh && git diff --check`

Commit: `fix: quiesce updater before setup mutations`.
