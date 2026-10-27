# Safe Uninstaller Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make uninstall predictable, idempotent, and non-destructive by default, with explicit confirmed purge.

**Architecture:** Keep `uninstall.sh` as the compatibility entry point and put the testable lifecycle in a standalone `installer/uninstall.py`. The Python CLI resolves canonical paths without evaluating `paths.env` as shell code, validates them before any side effect, prints the exact plan, and requires confirmation before removing service/application files. `--purge` adds config/data/backup deletion and a second typed confirmation.

**Tech Stack:** Bash, Python 3 standard library, pytest.

**Spec:** `docs/superpowers/specs/2026-10-28-safe-install-lifecycle-design.md` (Issue #28 work unit)

## Global Constraints

- Preserve `/etc/knx_to_openhab`, `/var/lib/knx_to_openhab`, and `/var/backups/knx_to_openhab` by default.
- Read only `KNXOH_INSTALL_DIR`, `KNXOH_CONFIG_DIR`, `KNXOH_DATA_DIR`, and `KNXOH_BACKUP_DIR`; do not `source` the saved path file.
- Reject root, relative, overlapping, and application-nested external paths before deletion.
- Existing partial removal and repeated execution must be safe.

## Review Focus

- Missing or malformed `paths.env`: use documented defaults or fail before side effects; test default and malformed values.
- Paths containing spaces, quotes, dollar signs, or backslashes: preserve exact values; test parser round-trip.
- A configured path equal to `/`, `/etc`, or nested beneath the install directory: refuse before deletion; test unsafe parameters.
- Missing services/files on a second run: report and continue without error; test idempotence.
- Purge without the exact typed confirmation: preserve all user data; test decline and wrong confirmation.

---

### Task 1: Resolve and validate uninstall paths

**Files:**
- Create: `installer/uninstall.py`
- Test: `tests/test_uninstall.py`

**Interfaces:**
- Produces `resolve_uninstall_paths(env: Mapping[str, str], paths_file: Path) -> UninstallPaths`; Task 2 consumes this interface for the CLI.

- [x] Write tests for saved-file parsing without shell execution, default paths, quoted paths, and unsafe/overlapping paths.
- [x] Run `python -m pytest -q tests/test_uninstall.py`; verify the new behavior fails before implementation.
- [x] Implement the standalone path resolver and validation.
- [x] Run `python -m pytest -q tests/test_uninstall.py`; expect all new path tests to pass.
- [x] Commit: `feat: add validated uninstall path resolution`.

### Task 2: Add safe default and explicit purge flow

**Files:**
- Modify: `uninstall.sh`
- Test: `tests/test_uninstall.py`

**Interfaces:**
- CLI in `installer/uninstall.py`: default uninstall; optional `--purge`; reject unknown options. Ordinary uninstall retains the service account and all external user data.

- [x] Add subprocess tests with a temporary fake `sudo`/`systemctl`/`rm` PATH; assert the printed file list, confirmation requirement, and exact deletion targets.
- [x] Run the focused tests on Linux CI or a Bash-capable host and observe expected failures against the old destructive behavior.
- [x] Implement `uninstall.sh` as a local launcher and `curl | bash` compatibility wrapper for the standalone Python CLI; use validation-before-side-effects, plan output, interactive confirmation, guarded removal, and a second exact `PURGE` confirmation.
- [x] Verify default mode retains config/data/backups, purge removes only the configured locations, and repeated runs succeed.
- [x] Commit: `fix: make uninstall non-destructive by default`.

### Task 3: Document and verify user-facing behavior

**Files:**
- Modify: `installer/README.md`
- Modify: `docs/PRODUCTION_GUIDE.md`
- Test: `tests/test_uninstall_docs.py`

- [x] Add assertions that documentation describes the default retention and `--purge` confirmation.
- [x] Replace destructive manual uninstall guidance with the supported safe command and explain retained data.
- [x] Run the uninstall tests, Bash syntax check, and `git diff --check`.
- [x] Commit: `docs: explain safe uninstall and purge`.

---
