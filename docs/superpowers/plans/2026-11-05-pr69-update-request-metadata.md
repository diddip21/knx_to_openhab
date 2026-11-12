# PR #69 Update Request Metadata Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reject control characters in commit messages and authors before the Web UI publishes an update request that its worker will later reject.

**Architecture:** Apply the same control-character rule in `Updater.trigger_update()` as `installer/run_update_request.py` uses. Validate before creating or linking the durable request file; keep the request schema unchanged.

**Tech Stack:** Python 3.12+, pytest, existing update-request filesystem fixtures.

**Spec:** `docs/superpowers/specs/2026-11-05-pr69-review-followups-design.md`

## Global Constraints

- Reject control characters below U+0020 except tab, matching the worker's current validation.
- Perform validation before request publication and worker startup.
- Do not change the request schema or normalize invalid GitHub metadata silently.

## Review Focus

- A carriage return/newline or NUL in the selected commit message is rejected without publishing a request (`test_trigger_update_rejects_control_characters_before_queueing`).
- Control characters in the author are rejected under the same policy (same parameterized test).
- Valid metadata and existing invalid-hash validation continue to work (`test_trigger_update_rejects_invalid_commit_metadata_before_queueing`, `test_build_metadata_release_update_is_not_suppressed`).

---

### Task 1: Validate metadata before request publication

**Files:**
- Modify: `web_ui/backend/updater.py`
- Test: `tests/test_updater.py`
- Reference: `installer/run_update_request.py::_validate_request`

**Interfaces:**
- Add a private control-character predicate in `web_ui/backend/updater.py` or reuse an existing shared helper if one exists.
- Apply it to both `commit_message` and `author` in `Updater.trigger_update()` before writing the temporary request.

- [x] **Step 1: Write the failing parameterized test**

Add `test_trigger_update_rejects_control_characters_before_queueing`, covering `\r` and `\x00` in both `commit_message` and `author`. Assert the call fails, worker startup is not called, and neither pending nor running request files are created.

- [x] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_updater.py::test_trigger_update_rejects_control_characters_before_queueing -q`
Expected: FAIL because `trigger_update()` currently accepts these metadata values.

- [x] **Step 3: Apply the worker's validation rule before publication**

Reject any character where `ord(character) < 32` unless it is `\t`, for both fields. Keep the existing type and length checks and return field-specific validation errors.

- [x] **Step 4: Run focused updater tests**

Run: `pytest tests/test_updater.py tests/test_run_update_request.py -q`
Expected: all publisher and worker validation tests pass with matching policy.

- [x] **Step 5: Commit the metadata validation change**

Use commit message: `fix: reject control characters in update metadata`.
