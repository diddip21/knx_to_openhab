# Recovery Command Quoting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make updater setup and sudoers-migration instructions copy-paste safe when the active install path contains whitespace.

**Architecture:** Use Bash `printf %q` on the complete active `installer/setup.sh` and `installer/migrate_sudoers.sh` paths and print each resulting command without wrapping the whole command in decorative quotes.

**Tech Stack:** Bash, pytest.

**Spec:** `docs/superpowers/specs/2026-11-05-pr69-review-followups-design.md`

## Global Constraints

- Resolve setup scripts from `$APP_DIR`, preserving active-release recovery behavior.
- Keep existing messages actionable and use the supported `sudo bash` invocation.
- Preserve legacy-install fallback and avoid changing update control flow.

## Review Focus

- Install paths with spaces produce a command that shell parsing resolves to `sudo`, `bash`, and the full script path.
- Transactional installs continue to reference the active release path, not `$INSTALL_DIR`.
- Recovery messages without whitespace remain valid and readable.

---

### Task 1: Shell-escape setup and migration recovery commands

**Files:**
- Modify: `update.sh`
- Test: `tests/test_privilege_policy.py`

**Interfaces:**
- Create setup and migration command strings from `sudo bash` plus `printf %q` of the full `$APP_DIR/installer/...` path.
- Use the corresponding string at every recovery site that directs the operator to run either installer script.

- [x] **Step 1: Write the failing path-with-spaces regression**

Add parameterized `test_update_recovery_command_quotes_install_path_with_spaces`. Run `update.sh` against a temporary installation named `install with spaces`, trigger both sudoers-migration and missing-venv recovery branches, and assert each emitted command shell-parses back to the complete active script path.

- [x] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_privilege_policy.py::test_update_recovery_command_quotes_install_path_with_spaces -q`
Expected: FAIL because current output contains unescaped spaces in `$APP_DIR`.

- [x] **Step 3: Escape and print the complete recovery command**

Use Bash `printf %q` on each full script path and print `sudo bash <escaped-path>` as a copyable command at all migration/setup guidance sites.

- [x] **Step 4: Run focused tests and shell syntax**

Run: `pytest tests/test_privilege_policy.py -q`
Expected: all privilege-policy and recovery-guidance tests pass.

Run: `bash -n update.sh`
Expected: no output and exit status 0.

- [x] **Step 5: Commit**

Use commit message: `fix: quote updater recovery script paths`.
