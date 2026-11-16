# PR #69 CI Test-Fixture Correction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the root-run core tests stable on Ubuntu 26 without changing production behavior or weakening maintenance-lock validation.

**Architecture:** Align systemd fixture filesystem state with its mocked `LoadState`; make the shared-directory test accept either valid rejection diagnostic. Keep the changes inside test files.

**Tech Stack:** Bash, Python 3.12/3.13, pytest.

**Spec:** `docs/superpowers/specs/2026-11-11-pr69-ci-test-fixture-design.md`

## Global Constraints

- Do not modify production code or relax the maintenance-lock ancestor checks.
- Keep `/dev/null` symlink coverage for units mocked as masked.
- Preserve coverage that loaded units are installed and configured service units receive the configured paths file.

## Review Focus

- Masked systemd units: ensure `/dev/null` symlinks remain untouched and are not started.
- Loaded systemd units: start with a regular existing unit and verify it is replaced by the managed content.
- Runtime-masked units: retain the existing regular-file preservation test.
- Configured paths containing spaces: retain the `EnvironmentFile` escaping checks.
- Shared lock parents under differing runner permissions: ensure validation still returns 2 and rejects the path for either recognized reason.

---

### Task 1: Stabilize root-run installer tests

**Files:**
- Modify: `tests/test_setup_unit_masks.py`
- Modify: `tests/test_maintenance_lock.py`
- Reference: `docs/superpowers/specs/2026-11-11-pr69-ci-test-fixture-design.md`

**Interfaces:**
- Consumes: `run_setup_unit_manager(tmp_path, unit, load_state, ...)` and `run_lock_script(lock_file, body)`.
- Produces: fixtures whose on-disk state matches the mocked systemd state, and rejection assertions that preserve the return-code and safety contract.

- [x] **Step 1: Correct the systemd fixture**

In `run_setup_unit_manager`, create a `/dev/null` symlink only when `load_state == "masked"`. For a loaded unit, initialize a regular existing unit file; leave the `runtime_mask=True` fixture behavior intact. Keep assertions that masked symlinks are preserved and that loaded units end with the managed file contents.

- [x] **Step 2: Broaden only the expected lock diagnostic**

In `test_lock_validation_refuses_common_shared_system_directories`, continue asserting `returncode == 2` and accept stderr containing either `dedicated` or `untrusted writable ancestor`.

- [x] **Step 3: Run focused tests**

Run: `./.venv/bin/pytest -q tests/test_setup_unit_masks.py tests/test_maintenance_lock.py`

Expected: all focused tests pass; masked, runtime-masked, configured-path, and lock rejection behavior remain covered.

- [x] **Step 4: Run the full root-run core test command and diff checks**

Run: `sudo -n env "PATH=$PATH" "$(command -v ./.venv/bin/pytest)" -q --cov=. --cov-report=xml -m "not ui" --ignore=tests/ui`

Also run: `git diff --check`

Expected: core suite exits 0 and the diff check reports no whitespace errors. If this environment lacks `sudo`, invoke the same pytest command directly as root and report that substitution.

- [x] **Step 5: Commit**

Commit the design, plan, and test-only changes with a focused message such as `test: stabilize root-run installer checks`.
