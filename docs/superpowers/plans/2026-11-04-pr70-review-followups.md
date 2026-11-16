# PR #70 Review Follow-ups Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resolve the three new PR #70 review findings with regression tests while preserving the isolated updater and transactional release flow.

**Architecture:** Keep the existing release staging, systemd worker and UI polling architecture. Publish the app tree at its final release path before building its venv, resume rather than replace an existing pending request, and use the final success log marker as the UI's sole success signal.

**Tech Stack:** Bash, Python, pytest, JavaScript, Playwright.

**Spec:** `docs/superpowers/specs/2026-11-04-pr70-review-followups-design.md`

## Global Constraints

- Preserve the existing isolated systemd updater and transactional release activation.
- Never overwrite or discard an existing pending update request.
- Display update success only after health validation, on `Update completed successfully`.
- Do not redesign the updater service, request format, or release layout.

## Review Focus

- A moved release must have executable entry points whose interpreter shebangs point to the final release path. Test by invoking the published venv launcher in the transactional-update integration test.
- A stale request must remain intact and be startable when the worker is inactive. Test by seeding `update-request.json`, triggering an update, and verifying the worker-start command runs without changing/deleting that request.
- A concurrent request must not remove or replace the first request. Keep the concurrency regression test asserting request identity and cleanup ownership.
- An active updater must not be reported as a newly started second update. Test the existing-request path when the worker-start command reports that the service is already running.
- A failed health check must not open the UI success dialog. Test that the dialog stays closed on the restart log and opens only after the final success marker.

---

### Task 1: Keep virtualenv executables valid after release publication

**Files:**
- Modify: `update.sh`
- Test: `tests/test_privilege_policy.py::test_transactional_update_rolls_back_or_prunes_releases_after_health_check`

**Interfaces:**
- Consumes: Existing `STAGED_APP_DIR`, `NEW_RELEASE_DIR`, and `cleanup_release_staging` transaction variables.
- Produces: A complete release whose `venv` is created at `NEW_RELEASE_DIR/venv`, with cleanup retaining ownership until the release is activated.

- [ ] **Step 1: Write the failing regression test**

Extend the existing normal-path integration case so the fake `python3 -m venv` writes a `gunicorn` entry point with a shebang to its venv Python. After the update, invoke `current/venv/bin/gunicorn` and assert it exits successfully. Keep the fake entry point's interpreter path tied to the path passed to `venv` so the current move-from-staging behavior fails.

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest -q 'tests/test_privilege_policy.py::test_transactional_update_rolls_back_or_prunes_releases_after_health_check[False-False-False-False]'`

Expected: FAIL because the entry point's interpreter path points inside the removed `.staging-*` tree.

- [ ] **Step 3: Build the venv at the final path**

In `update.sh`, move the extracted app directory to `NEW_RELEASE_DIR` before running `python3 -m venv`; use that final directory for dependency installation, compilation, imports, and health-endpoint resolution. Extend the exit cleanup to remove an unpublished candidate on pre-activation failure, without deleting an active release.

- [ ] **Step 4: Run the integration test to verify it passes**

Run: `python -m pytest -q tests/test_privilege_policy.py::test_transactional_update_rolls_back_or_prunes_releases_after_health_check`

Expected: all parameter cases pass, including the final-path launcher invocation and failure cleanup cases.

---

### Task 2: Recover an existing pending update request safely

**Files:**
- Modify: `web_ui/backend/updater.py`
- Test: `tests/test_updater.py`

**Interfaces:**
- Consumes: Existing atomic hard-link publication and `start-web-update` helper.
- Produces: `trigger_update()` resumes an existing pending request without replacing or deleting it; a published request remains durable after worker-start errors, and an active worker is reported as pending/in progress.

- [ ] **Step 1: Write failing stale-request and active-worker tests**

Add a test that seeds a valid pending `update-request.json`, has the worker-start subprocess succeed, then asserts `trigger_update()` succeeds and the exact request bytes remain unchanged. Add/adjust tests where the service-start helper reports already active, both for a pre-existing request and a just-published request, and assert the request remains available and was not replaced or deleted.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest -q tests/test_updater.py -k 'pending_request or concurrent_update_request'`

Expected: the stale-request test fails because `FileExistsError` currently returns before starting the worker.

- [ ] **Step 3: Resume without taking ownership of the existing file**

In `trigger_update()`, resume a pre-existing request before querying GitHub, and distinguish a newly published request from an existing one. Never truncate the existing log, overwrite a request, or delete a published request after a worker-start error; ask the existing service helper to start the worker and return an accurate pending/in-progress response. Keep request-ID guarded cleanup only for a request whose log could not be prepared before worker startup.

- [ ] **Step 4: Run updater tests to verify they pass**

Run: `python -m pytest -q tests/test_updater.py`

Expected: all updater tests pass, including the concurrent-publisher regression.

---

### Task 3: Signal UI success only after health validation

**Files:**
- Modify: `web_ui/static/app.js`
- Test: `tests/ui/test_update_system.py`
- Create: `docs/screenshots/pr70-update-success-dialog.png`

**Interfaces:**
- Consumes: Existing `/api/version/log` polling and `Update completed successfully` log marker.
- Produces: The success dialog and reload countdown begin only after the final success marker.

- [ ] **Step 1: Write the failing UI regression test**

Add a Playwright test whose mocked log initially contains `Restarting knxohui.service` and later contains `Update completed successfully`. Assert the success dialog remains closed after the restart message, then opens after the success marker.

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest -q tests/ui/test_update_system.py -k success_dialog_waits_for_health_validation`

Expected: FAIL because the current UI opens the success dialog on the restart message.

- [ ] **Step 3: Use only the final success marker**

Update the success predicate in `web_ui/static/app.js` to trigger only when the log includes `Update completed successfully`.

- [ ] **Step 4: Run the UI test to verify it passes**

Run: `python -m pytest -q tests/ui/test_update_system.py -k success_dialog_waits_for_health_validation`

Expected: PASS; restart alone keeps the dialog closed, final success opens it.

- [ ] **Step 5: Save the required UI screenshot**

Capture the success dialog from the passing Playwright test at `docs/screenshots/pr70-update-success-dialog.png`; verify the screenshot contains only the finished UI state and no secrets or personal data.

---

### Task 4: Verify the complete PR change set

**Files:**
- Verify: all files above and existing PR #70 changes.

- [ ] Run focused regression coverage: `python -m pytest -q tests/test_updater.py tests/test_privilege_policy.py tests/ui/test_update_system.py`.
- [ ] Run core tests: `python -m pytest -q -m 'not ui' --ignore=tests/ui`.
- [ ] Run formatting, lint, type checks, shell syntax, and `git diff --check` using repository CI commands.
- [ ] Push the verified commits to the PR #70 branch, reply to and resolve only the addressed review threads, and check all latest GitHub CI runs and review threads. Do not merge PR #70.
