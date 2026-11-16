# PR #70 Review Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the additional critical and important findings from the fresh PR #70 review without merging the PR.

**Architecture:** Keep the current filesystem queue, isolated systemd worker, and transactional release switch. Serialize request publication and worker ownership with one data-directory `flock`; use durable log ordering and a candidate marker so retries can distinguish current work from stale state.

**Tech Stack:** Python 3.12+, `fcntl.flock`, Bash, pytest, Playwright, vanilla JavaScript.

**Spec:** `docs/superpowers/specs/2026-11-04-pr70-review-followups-design.md` (Review-driven hardening section).

## Global Constraints

- Preserve the existing isolated systemd updater and transactional release activation.
- Both Web UI publication and the systemd worker use `update-request.lock` in the configured runtime data directory.
- Never delete a request or release currently owned by an active worker or selected by `current`.
- Initialize and fsync a request's log before publishing its request file.
- Retain health-check rollback and show success only for a completed update.
- Do not introduce a database or a new queue protocol.

## Review Focus

- Activation signal boundary: after the current symlink switches, cleanup must preserve that target even before the activation flag changes. Test by signaling after the atomic symlink switch.
- Abandoned final-path build: a candidate with `.update-in-progress` that is not current must be reclaimed on retry; an active marked candidate must be kept.
- Concurrent request and worker claim: a second trigger while publication or worker execution owns the lock must not publish, truncate the log, or overwrite either request path. Test with real file locks and the worker's lock lifetime.
- Interrupted worker claim: a stale `update-request.running.json` with a free lock must be restored and retried; if both pending and running files exist, preserve both and report the conflict.
- Old success in the log: a prior success marker must not open the UI dialog for a new or resumed request before its own health check passes. Test old-log → request reset/recovery → rollback and success.

---

### Task 1: Make release candidate cleanup activation-safe and recoverable

**Files:**
- Modify: `update.sh`
- Test: `tests/test_privilege_policy.py::test_transactional_update_rolls_back_or_prunes_releases_after_health_check`

**Interfaces:**
- Consumes: `APP_DIR`, `CURRENT_LINK`, `STAGING_DIR`, and `NEW_RELEASE_DIR` from the current transactional updater.
- Produces: `.update-in-progress` marker semantics, stale candidate cleanup, and an exit trap that never removes the selected release.

- [ ] **Step 1: Add failing candidate-recovery and activation-signal tests**

Extend the update integration fixture to seed a marked inactive candidate and assert it is removed; seed an active candidate/staging target and assert it is not removed. Add a fake `mv -Tf` that completes the switch and signals the updater before its activation flag assignment; assert `current` still resolves to an existing release directory.

- [ ] **Step 2: Run the focused cases to verify they fail**

Run: `python -m pytest -q tests/test_privilege_policy.py -k 'update_candidate or activation_signal'`

Expected: the active-target interruption case observes `current` pointing at a removed directory, and stale marked candidates remain.

- [ ] **Step 3: Mark, recover, and guard release candidates**

Create `.update-in-progress` inside the extracted app before moving it to `NEW_RELEASE_DIR`. Under the existing updater lock, remove marked inactive candidates and abandoned staging trees while excluding the resolved `current` target. In the EXIT trap, resolve `current` before deleting an unpublished `NEW_RELEASE_DIR`; preserve it whenever it is selected, regardless of `RELEASE_ACTIVATED`. Remove the new marker after health validation; do not retain an older marked candidate as a rollback release.

- [ ] **Step 4: Run release integration tests**

Run: `python -m pytest -q tests/test_privilege_policy.py::test_transactional_update_rolls_back_or_prunes_releases_after_health_check`

Expected: all normal, rollback, interruption, and cleanup parameter cases pass.

---

### Task 2: Serialize request publication and worker ownership

**Files:**
- Create: `update_request_lock.py`
- Modify: `web_ui/backend/updater.py`
- Modify: `installer/run_update_request.py`
- Test: `tests/test_updater.py`
- Test: `tests/test_run_update_request.py`

**Interfaces:**
- Produces: `update_request_lock(data_dir: Path, blocking: bool)` as a context manager yielding whether the lock was acquired; the UI uses non-blocking mode and the worker uses blocking mode.
- Worker lock lifetime: acquire before inspecting/claiming pending state, hold through updater execution and cleanup, release on every exit path.

- [ ] **Step 1: Add failing real-lock and stale-claim tests**

Test that a trigger cannot publish while the worker holds the lock; test that the worker holds the lock while its updater process is running; test that an inactive stale `update-request.running.json` is recovered, while simultaneous pending and running files are both preserved and reported.

- [ ] **Step 2: Run lock and worker tests to verify they fail**

Run: `python -m pytest -q tests/test_updater.py tests/test_run_update_request.py -k 'lock or running_request'`

Expected: the second request is currently publishable while the worker has claimed the first, and stale claimed work is discarded by `_claim_request()`.

- [ ] **Step 3: Share one lock and preserve request state**

Implement the lock context manager using a 0600 lock file at `data_dir/update-request.lock`. In `Updater.trigger_update()`, acquire non-blocking before checking pending/running files or changing the log; return an in-progress status if unavailable. When the lock is free, restore a lone stale running request to pending, refuse to discard conflicting request files, and retain published requests after start failures. In `run_update_request()`, acquire the same lock before claim and hold it through subprocess completion.

- [ ] **Step 4: Run request/worker regression suites**

Run: `python -m pytest -q tests/test_updater.py tests/test_run_update_request.py`

Expected: all request serialization, worker claim, and prior updater tests pass.

---

### Task 3: Make request logs and UI status belong to the current request

**Files:**
- Modify: `web_ui/backend/updater.py`
- Modify: `web_ui/static/app.js`
- Test: `tests/test_updater.py`
- Test: `tests/ui/test_update_system.py`
- Keep: `docs/screenshots/pr70-update-success-dialog.png`

**Interfaces:**
- Consumes: The request lock and pending/running recovery from Task 2.
- Produces: A durable per-attempt log header written before atomic request publication; a response identifying the actual resumed release; UI that displays the response and does not treat an old success marker or explicit startup error as current success.

- [ ] **Step 1: Add failing ordering and stale-log UI tests**

Use a test hook around atomic publication to assert the log has already been reset, fsynced, and identifies the selected tag. In Playwright, return an old success log before POST, switch to the newly queued header after POST, and assert the dialog stays closed until the new run's final success marker. Verify explicit API startup errors remain visible and do not get overwritten by polling. Make screenshot capture opt-in so routine UI runs do not rewrite the committed screenshot.

- [ ] **Step 2: Run the focused tests to verify they fail**

Run: `python -m pytest -q tests/test_updater.py -k 'log_before_publish or pending_request' tests/ui/test_update_system.py -k 'stale_success or startup_error'`

Expected: the old log can currently survive request publication and satisfy the UI's success substring check; explicit errors are replaced by polled logs.

- [ ] **Step 3: Establish the current request's log boundary and status**

While holding the request lock, write the new/resumed release header to `update.log`, flush and `fsync` it before publishing or starting the worker. Include the actual pending release tag in the response. In `performUpdate()`, show the response immediately; do not start log polling after an explicit API error. Keep success polling gated on the completed-update marker after the new request's log boundary. Capture the screenshot only when explicitly requested by the test environment.

- [ ] **Step 4: Run focused updater and UI tests**

Run: `python -m pytest -q tests/test_updater.py tests/ui/test_update_system.py`

Expected: old success cannot trigger the new dialog, resumed release identity is shown, and the committed screenshot is not modified by a normal test run.

---

### Task 4: Verify and update PR #70

**Files:**
- Verify: all files above and existing PR #70 changes.

- [ ] Run focused regression coverage: `python -m pytest -q tests/test_updater.py tests/test_run_update_request.py tests/test_privilege_policy.py tests/ui/test_update_system.py`.
- [ ] Run core tests: `python -m pytest -q -m 'not ui' --ignore=tests/ui`.
- [ ] Run Black, isort, flake8, mypy, `bash -n update.sh`, and `git diff --check`.
- [ ] Get a fresh whole-branch review; fix all Critical/Important issues with RED→GREEN tests.
- [ ] Push verified commits to PR #70, reply to and resolve addressed review threads, and recheck current GitHub CI and review threads. Keep PR #70 open and do not merge.
