# Gateway Review Follow-up Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resolve every valid finding on PR #55's current Codex review and merge only after a clean review and passing required CI.

**Architecture:** Keep the existing Flask/Python backend and vanilla-JS UI. Make rollback fail closed when backup metadata cannot identify the restored deployment, maintain exactly one active deployed-job flag, share the existing pure gateway-file parser for Undo responses, and reuse a quote-aware DSL comment scanner without dependencies.

**Tech Stack:** Python 3.12+, Flask, vanilla JavaScript, pytest, Playwright.

**Spec:** `docs/superpowers/specs/2026-10-31-gateway-review-followup-design.md`

## Global Constraints

- Do not add dependencies.
- Do not query OpenHAB runtime or network state.
- Preserve managed-file write safety and use lock order `operation_lock` then `gateway_state_lock` for deployment-state changes.
- After a successful deploy, persist only the newly deployed job with `deployed=true`; if metadata persistence fails, restore all prior deployment flags and the current job's identity fields.
- Do not infer a deployment or ETS identity from arbitrary backup file contents.
- Do not force-push; merge only after the current PR head has no unresolved review findings and required CI checks pass.

## Review Focus

- **Generic rollback from an arbitrary or legacy backup:** live actions must not target stale job metadata — Task 1 asserts all deployment targets are invalidated.
- **Valid non-canonical IPv6 input (`2001:0db8::1`):** later Save Config must retain the backend's canonical `2001:db8::1` — Task 3 checks the input and submitted config payload.
- **Unmanaged DSL with a bridge inside `/* ... */` comments:** do not block migration for commented examples, but still find active declarations — Task 4 covers both.
- **Undo with an empty prior saved override and an IP in the prior file:** return the restored file IP while keeping the override empty — Task 5 asserts both response fields.
- **A live managed-file edit after backup followed by a rejected format preflight:** the rejection must not restore stale backup contents — Task 2 simulates this ordering.
- **System clock moves backwards before a second deploy:** the newly written target remains active even if its `deployed_at` is smaller — Task 10 pins the active flag behavior.
- **Metadata persistence fails after a replacement deploy:** restore every prior active flag and the redeployed job's previous timestamp/identity — Task 10 extends failure coverage.
- **Delete or save invalidates gateway Undo/target state:** refresh the Devices view and action controls after the successful mutation — Task 11 covers both transitions.
- **A DSL bridge exists only inside a block comment, or beside a live bridge:** edits reject the commented-only case and modify only the live bridge — Task 12 covers both.
- **Comment delimiters occur inside quoted DSL strings:** preserve and recognize active declarations — Task 12 exercises the shared scanner's quote handling.

---

### Task 1: Invalidate gateway deployment state after generic rollback

**Files:**
- Modify: `web_ui/backend/jobs.py:1417-1461`
- Test: `tests/test_web_ui_job_stats.py`
- Reference: `web_ui/backend/gateway_undo.py`

**Interfaces:**
- `JobManager.rollback(job_id, backup_name=None)` remains the public API.
- A successful generic rollback invalidates every job's `deployed` flag; a failed metadata save aborts before restoring files. If restore fails after invalidation, remain fail-closed. Clear the live Undo snapshot after successful restore.

- [x] **Step 1: Write the failing regression test**

Add `test_rollback_invalidates_gateway_deployment_metadata_and_undo_snapshot`. Prepare a valid managed-file backup and multiple jobs marked deployed, including gateway source/target metadata; save an Undo snapshot. After rollback assert restored bytes, all persisted deployed flags are false, `get_last_deployed_things_target()` and `get_last_deployed_gateway_source()` return `None`, and the snapshot is removed.

- [x] **Step 2: Run the test and confirm it fails on stale metadata**

Run: `python -m pytest -q tests/test_web_ui_job_stats.py::test_rollback_invalidates_gateway_deployment_metadata_and_undo_snapshot`

Expected: FAIL because the current rollback leaves deployed-job metadata and the Undo snapshot active.

- [x] **Step 3: Implement fail-closed rollback metadata handling**

Acquire `operation_lock` then `gateway_state_lock` in `rollback`. Validate the selected backup before mutation. Persist all deployed flags as false before restoring files; restore in-memory flags and abort if that save fails. If restoration fails, leave metadata invalidated. After a successful restore, clear the Undo snapshot (log cleanup failure without re-exposing a target).

- [x] **Step 4: Run the test and verify it passes**

Run: `python -m pytest -q tests/test_web_ui_job_stats.py::test_rollback_invalidates_gateway_deployment_metadata_and_undo_snapshot`

Expected: PASS; no gateway target/source or usable Undo snapshot remains after rollback.

- [x] **Step 5: Commit**

```bash
git add tests/test_web_ui_job_stats.py web_ui/backend/jobs.py
git commit -m "fix: invalidate gateway target after rollback"
```

### Task 2: Keep deploy preflight rejection outside rollback recovery

**Files:**
- Modify: `web_ui/backend/jobs.py:1548-1584`
- Test: `tests/test_things_format_jobs.py`

**Interfaces:**
- Keep `assert_no_unmanaged_bridge_definitions(openhab_path, managed_things_relpaths)` under the deployment locks and immediately before staged writes.

- [x] **Step 1: Write the failing regression test**

Extend the format-switch deploy test to make the preflight scanner create an unmanaged bridge and simulate a managed-file edit after the pre-deploy backup. Assert the bridge rejection raises, `restore_managed_files` is not called, and the later managed-file edit remains intact.

- [x] **Step 2: Run the test and confirm it fails**

Run: `python -m pytest -q tests/test_things_format_jobs.py::test_format_switch_preflight_rejection_does_not_restore_backup`

Expected: FAIL because the current exception handler restores the preflight backup.

- [x] **Step 3: Move preflight validation outside the deployment rollback `try`**

Keep the format-switch scan after backup creation and before the staged writer, but outside the `try` whose exception handler calls `restore_managed_files`.

- [x] **Step 4: Run the regression and existing partial-deploy rollback test**

Run: `python -m pytest -q tests/test_things_format_jobs.py::test_format_switch_preflight_rejection_does_not_restore_backup tests/test_things_format_jobs.py::test_format_switch_rolls_back_both_files_on_partial_deploy_failure`

Expected: PASS; preflight rejects without writes, while an actual partial deployment still rolls back.

- [x] **Step 5: Commit**

```bash
git add tests/test_things_format_jobs.py web_ui/backend/jobs.py
git commit -m "fix: avoid rollback on deploy preflight rejection"
```

### Task 3: Keep the canonical gateway override in UI state

**Files:**
- Modify: `web_ui/static/app.js:1377-1402`
- Test: `tests/ui/test_gateway_live_update.py`
- Create: `docs/screenshots/gateway-ip-canonicalized.png` (opt-in Playwright screenshot)

**Interfaces:**
- Use the existing apply response field `saved_override`; keep the raw input only as a fallback for older responses.

- [x] **Step 1: Write the failing browser regression test**

Add `test_live_apply_saves_backend_canonical_ipv6_override`. Have the apply route return `saved_override: "2001:db8::1"` for input `"2001:0db8::1"`; after Apply, assert the field is canonical, click **Save Config**, and assert the submitted `devices.gateway.ip_address` is canonical.

In the same test, capture the finished settings view to `docs/screenshots/gateway-ip-canonicalized.png` only when `SAVE_UI_SCREENSHOTS=1`; use safe documentation IPv6 data and no credentials.

- [x] **Step 2: Run the UI test and confirm it fails**

Run: `python -m pytest -q tests/ui/test_gateway_live_update.py::test_live_apply_saves_backend_canonical_ipv6_override -o addopts=`

Expected: FAIL because Apply currently leaves the original spelling in the field and `currentConfig`.

- [x] **Step 3: Store the returned canonical value**

In `applyGatewayIpLive`, use `result.saved_override` (falling back to the request only if absent) for both `#conf-gateway-ip` and `currentConfig.devices.gateway.ip_address`.

- [x] **Step 4: Run the UI regression**

Run: `python -m pytest -q tests/ui/test_gateway_live_update.py::test_live_apply_saves_backend_canonical_ipv6_override -o addopts=`

Expected: PASS; the field and saved API payload use `2001:db8::1`.

- [x] **Step 5: Capture and inspect the UI screenshot**

Run the focused browser test with `SAVE_UI_SCREENSHOTS=1`. Confirm the screenshot shows the canonicalized gateway IP in the real app UI and contains no secrets or personal data.

- [x] **Step 6: Commit**

```bash
git add tests/ui/test_gateway_live_update.py web_ui/static/app.js docs/screenshots/gateway-ip-canonicalized.png
git commit -m "fix: preserve canonical gateway IP in UI"
```

### Task 4: Ignore bridge declarations in DSL comments

**Files:**
- Modify: `web_ui/backend/things_format.py:9-47`
- Test: `tests/test_things_format_jobs.py`

**Interfaces:**
- Add a private comment-stripping helper used by `find_unmanaged_bridge_definitions`; preserve line boundaries and quoted strings, and fail closed on unterminated block comments.

- [x] **Step 1: Write failing DSL comment tests**

Add tests proving a bridge only inside a multiline block comment is ignored, an active bridge after a closed comment is still detected, comment markers inside quoted strings do not hide declarations, and an unterminated block comment fails closed with the file path.

- [x] **Step 2: Run the new tests and confirm they fail**

Run: `python -m pytest -q tests/test_things_format_jobs.py -k "block_comment or quoted_comment_markers"`

Expected: FAIL because the scanner currently matches declarations inside block comments.

- [x] **Step 3: Implement the small quote-aware DSL comment scanner**

Strip `//` and `/* ... */` comments before matching `_DSL_BRIDGE`; retain newlines, do not treat markers inside single- or double-quoted strings as comments, and reject an unterminated block comment with the unmanaged file path.

- [x] **Step 4: Run scanner tests and the full format-job test module**

Run: `python -m pytest -q tests/test_things_format_jobs.py`

Expected: PASS, including existing DSL/YAML bridge-migration cases. On this
Windows host, the module had 20 passing tests and one pre-existing
POSIX-path-validation failure also present in the baseline.

- [x] **Step 5: Commit**

```bash
git add tests/test_things_format_jobs.py web_ui/backend/things_format.py
git commit -m "fix: ignore commented DSL bridge declarations"
```

### Task 5: Report the restored file IP from Undo

**Files:**
- Modify: `web_ui/backend/gateway_config.py:260-302`
- Modify: `web_ui/backend/jobs.py:601-642`
- Test: `tests/test_gateway_live_update.py`

**Interfaces:**
- Expose `read_gateway_config(content: str, format_name: str) -> tuple[str | None, str | None]` as the shared pure parser for `(gateway_ip, gateway_mode)`.
- Keep `saved_override` separate from the IP read from the restored file.

- [x] **Step 1: Write the failing Undo response regression**

Add `test_undo_reports_restored_file_ip_when_previous_override_is_empty`. Start with an empty persisted override and a previous managed file containing an ETS tunnel IP, apply a different IP, then undo. Assert `result["gateway_ip"]` is the prior file IP and `result["saved_override"] == ""`.

- [x] **Step 2: Run the test and confirm it fails**

Run: `python -m pytest -q tests/test_gateway_live_update.py::test_undo_reports_restored_file_ip_when_previous_override_is_empty`

Expected: FAIL because Undo currently returns `None` for `gateway_ip` when the saved override is empty.

- [x] **Step 3: Reuse the shared parser for the previous bytes**

Expose the existing `_read_gateway_config` behavior as `read_gateway_config`, use it from `read_gateway_state`, and parse the snapshot's `previous_content` before any writes in `undo_gateway_ip`. Return the parsed gateway IP while preserving `previous_override` in `saved_override`.

- [x] **Step 4: Run Undo and gateway parser regressions**

Run: `python -m pytest -q tests/test_gateway_live_update.py`

Expected: PASS on supported POSIX CI; locally 78 passed and three unrelated
Windows path failures remained, matching the baseline.

- [x] **Step 5: Commit**

```bash
git add tests/test_gateway_live_update.py web_ui/backend/gateway_config.py web_ui/backend/jobs.py
git commit -m "fix: report restored gateway file IP after undo"
```

### Task 6: Verify, publish, and apply the review gate

**Files:**
- Include: `docs/superpowers/specs/2026-10-31-gateway-review-followup-design.md`
- Include: `docs/superpowers/plans/2026-10-31-gateway-review-followup.md`

- [x] Run all focused backend regressions from Tasks 1, 2, 4, and 5.
- [x] Run the focused Playwright regression from Task 3 and applicable UI tests.
- [x] Run the full pytest suite, `python -m black --check .`, isort/flake8 on changed Python files, and `git diff --check`; report Windows-only failures accurately. Full suite on this Windows host: 639 passed, 23 skipped, 46 failed; failures trace to POSIX-only APIs/path semantics, symlink permissions, Bash path handling, and a locked UI fixture. Baseline before implementation had the same 46 Windows/POSIX failures.
- [x] Run a fresh read-only code-review subagent against the completed commit range; fix any Critical or Important issue before publishing. Review of `62c9a93..86e73eb` approved with no findings.
- [x] Commit the design and plan documents with a conventional `docs:` commit (`fb649e3`).
- [ ] Reference the committed screenshot from the PR with a short explanation of the view.
- [ ] Push to `feat/live-knx-gateway-ip-dsl-yaml` with a normal fast-forward push; never force-push.
- [ ] Reply to each new GitHub finding with its disposition and resolve only findings addressed by the final code.
- [ ] Request `@codex review` on the resulting PR head. Merge only when Codex reports no unresolved findings and all required CI checks pass; otherwise stop and report the remaining blocker.

### Follow-up tasks for review findings on `0548a86`

#### Task 7: Invalidate deployment state when deleting the active job

**Files:**
- Modify: `web_ui/backend/jobs.py:1681-1701`
- Test: `tests/test_web_ui_job_stats.py`

- [x] Add regression coverage with a deployed active job, older deployed history, and an Undo snapshot. Delete the active job and assert the job is removed, all deployment targets/sources are unavailable, and the snapshot is cleared rather than falling back to older metadata.
- [x] Add/retain a persistence-failure assertion that deletion and invalidation are not partially applied in memory.
- [x] Implement under `operation_lock` then `gateway_state_lock` then `lock`; persist invalidation before removing the active record, and clear Undo only after successful persistence.
- [x] Run focused tests and format/lint checks; commit with a conventional `fix:` message.

#### Task 8: Restore previous deployment metadata after failed persistence

**Files:**
- Modify: `web_ui/backend/jobs.py:1592-1617`
- Test: `tests/test_web_ui_job_stats.py`

- [x] Add a regression that fails only the post-write metadata save during a same-job redeploy. Assert live bytes are restored, prior deployment fields remain in memory and on disk, and the prior gateway target/source and Undo identity remain usable.
- [x] Restore the previous `deployed`, `deployed_at`, and `deployment_id` values when the metadata save fails, while retaining the existing backup recovery path.
- [x] Run focused tests and format/lint checks; commit with a conventional `fix:` message.

#### Task 9: Refresh gateway state after deploy and rollback

**Files:**
- Modify: `web_ui/static/app.js:296-350`
- Test: `tests/ui/test_gateway_live_update.py`
- Create: `docs/screenshots/gateway-state-after-rollback.png` (opt-in Playwright screenshot)

- [x] Add browser regressions proving successful deploy and rollback each issue a new gateway-state request and render the returned target/availability.
- [x] Await `loadGatewayState()` after each successful transition so stale controls/paths are not shown. Do not treat failed operations as successful transitions.
- [x] Capture and inspect `gateway-state-after-rollback.png` with safe sample addresses and no credentials/personal data.
- [x] Run focused UI tests and relevant UI suite; commit with a conventional `fix:` message.

### Follow-up findings on `023ad49`

#### Task 10: Keep exactly one deployed job active

**Files:**
- Modify: `web_ui/backend/jobs.py:1493-1626`
- Test: `tests/test_web_ui_job_stats.py`

**Interfaces:**
- Keep the existing `JobManager.deploy(job_id)` and target/source getter APIs.
- `deployed` identifies the current active deployment. A successful deploy clears that flag from every other job before persisting the new active job.

- [x] Add `test_successful_deploy_selects_new_job_when_clock_moves_backward`: start with an older deployed job, mock `time.time()` to a smaller timestamp, deploy a staged new job, and assert only the new job is deployed and both gateway target/source getters resolve to it.
- [x] Extend the failed same-job redeploy regression to include another previously deployed job; fail only the final metadata save and assert all prior `deployed` flags, timestamp/ID fields, persisted target/source and Undo identity are restored while file bytes roll back.
- [x] Implement a snapshot/restore of every job's prior `deployed` flag. On successful file write, clear other flags and mark the current job active in the same metadata save; on exception, restore all flags and the current job's prior `deployed_at` and `deployment_id` before restoring live files.
- [x] Run the focused success and persistence-failure tests, then the affected backend test modules; run Black/isort/flake8 and commit with a conventional `fix:` message.

#### Task 11: Refresh gateway UI after delete and config save

**Files:**
- Modify: `web_ui/static/app.js:275-294,1648-1764`
- Test: `tests/ui/test_gateway_live_update.py`
- Create: `docs/screenshots/gateway-state-after-job-delete.png`
- Create: `docs/screenshots/gateway-undo-disabled-after-config-save.png`

- [x] Add browser regressions proving successful deletion refreshes an invalidated target and disables Apply/Reset/Undo, and successful config save refreshes `undo_available` after changing the saved override.
- [x] After successful deletion, await both the jobs refresh and `loadGatewayState()`; after successful config persistence and assigning `currentConfig`, await `loadGatewayState()`. Do not refresh as if a failed save/delete succeeded.
- [x] Capture and inspect safe sample-state screenshots for both transitions with no credentials or personal data.
- [x] Run both focused browser tests and the gateway UI module; run `node --check web_ui/static/app.js` and commit with a conventional `fix:` message.

#### Task 12: Ignore commented bridge examples in live DSL edits

**Files:**
- Modify: `web_ui/backend/things_format.py:12-75`
- Modify: `web_ui/backend/gateway_config.py:14-104`
- Test: `tests/test_gateway_live_update.py`
- Test: `tests/test_things_format_jobs.py`

**Interfaces:**
- Expose the existing scanner as `strip_dsl_comments(content: str, source: str | Path = "DSL content") -> str`, preserving string length and line endings; retain source-specific fail-closed errors for unmanaged-file scanning.
- `_dsl_bridge_config(content)` uses the stripped view for declaration and bracket discovery but returns offsets/slices into the original content. Property and segment discovery also uses the stripped view; edits are applied at matching source offsets and preserve comments.

- [x] Add regressions for Apply and Reset with one live bridge plus a block-commented duplicate (only live content changes), commented-only bridges, comment-like property examples inside the live configuration, and markers inside quoted strings.
- [x] Reuse the existing quote-aware scanner for live DSL declaration, boundary, property, and segment discovery without changing YAML handling or stripping comments from output.
- [x] Run the focused gateway parser/live-edit tests and `tests/test_things_format_jobs.py`; run Black/isort/flake8 and commit with a conventional `fix:` message.

#### Task 13: Verify, publish, and reapply the review gate

- [x] Run focused regressions for Tasks 10–12, the relevant backend/UI modules, the full local pytest suite, formatter/lint checks, `node --check`, and `git diff --check`; document known Windows-only failures against the recorded baseline.
- [x] Run a fresh read-only whole-range review and address any Critical or Important finding.
- [ ] Commit the approved design/plan documentation, fetch the remote branch, verify it is an ancestor, and push normally without force.
- [ ] Reply to and resolve only the four Codex threads fixed by Tasks 10–12; link both screenshots in the PR with descriptions.
- [ ] Request a fresh `@codex review` on the pushed head. Merge only after that review has no unresolved findings and all required CI checks pass.
