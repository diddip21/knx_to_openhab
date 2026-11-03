# Issue #25 Installer Preflight Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fail early with actionable errors when the host cannot run or complete installation, before cloning application files or running setup.

**Architecture:** Add named preflight functions directly to standalone `install.sh`. Check prerequisites in stages: OS/Python/disk and release connectivity before apt; create and remove a temporary venv after package installation but before clone/setup. Keep release-network probing mode-aware.

**Tech Stack:** Bash, existing Python 3 interpreter, pytest subprocess tests; no new runtime dependency.

**Spec:** `docs/superpowers/specs/2026-11-03-issue-25-installer-preflight-design.md`

## Global Constraints

- Preserve existing `--install`, `--update`, `--repair`, and `--cancel` behavior.
- A failing check must stop with a specific diagnostic and nonzero status before its corresponding downstream side effects.
- Only install/update require GitHub release network access; repair still runs the existing apt dependency flow and is not promised to work fully offline.
- Do not add runtime dependencies or claim that this PR makes all setup operations idempotent.
- Keep the current Python 3.11-compatible installer floor; the application code itself is tested in CI on Python 3.12 and 3.13.

## Review Focus

- `--help` and `--cancel` must not run checks or mutate the machine — pin in Task 1.
- A missing or unsupported Python must be diagnosed before apt/checkout — pin in Task 1.
- An installation path that does not yet exist must still check the filesystem of its nearest existing parent — pin in Task 1.
- A repair must skip the GitHub release probe, while install/update must perform it — pin in Task 1.
- Missing/broken `venv` support after package setup must be detected before clone/setup, and temporary probe data must be removed — pin in Task 2.

---

### Task 1: Pre-package host and release preflight

**Files:**
- Modify: `install.sh`
- Test: `tests/test_installer_preflight.py`
- Modify: `docs/superpowers/specs/2026-11-03-issue-25-installer-preflight-design.md`

**Interfaces:**
- `install.sh` exposes `run_installer_preflight <mode> <install-dir>` for tests and calls it in its main flow.
- The existing `check_os` remains responsible for OS detection; preflight uses the existing `python3`, `df`, and `curl`. Use a single documented free-space floor of 1 GiB on the filesystem that will contain the install directory.
- For a not-yet-created install path, resolve its nearest existing parent before querying free space.
- Host Python must be at least 3.11. The helper should explain that this interpreter is needed by the installer itself.
- Install/update probe HTTPS reachability of the public GitHub repository before apt; repair skips this release probe.

- [ ] **Step 1: Add failing helper tests**

Add tests for supported host/Python, missing or too-old Python, disk space just below and exactly at the 1 GiB floor, unreachable GitHub, repair skipping GitHub, and absent install-dir parent resolution. Source `install.sh` under its existing main guard and use temporary fake commands for deterministic behavior; assert actionable errors and nonzero status on failures.

- [ ] **Step 2: Run focused tests and confirm expected failures**

Run: `.venv/bin/python -m pytest tests/test_installer_preflight.py -q -o addopts=''`
Expected: FAIL because `run_installer_preflight` is not implemented.

- [ ] **Step 3: Implement the minimal pre-package helper**

Implement `run_installer_preflight <mode> <install-dir>` with named checks and stable nonzero failures. Treat missing `ID_LIKE` safely under `set -u`; retain the current Debian-family support and warning/prompt behavior for other systems rather than broadening supported OSes.

- [ ] **Step 4: Wire checks into `install.sh`**

Keep mode validation, `--help`, and `--cancel` ahead of preflight. Run host/Python/disk/release-network checks after mode/OS/sudo/release selection but before `install_dependencies`. Avoid a duplicate GitHub probe for repair.

- [ ] **Step 5: Run helper and installer mode tests**

Run: `.venv/bin/python -m pytest tests/test_installer_preflight.py tests/test_installer_modes.py -q -o addopts=''`
Expected: PASS; existing no-sudo/no-mutation mode tests remain green.

- [ ] **Step 6: Commit**

```bash
git add install.sh tests/test_installer_preflight.py docs/superpowers/specs/2026-11-03-issue-25-installer-preflight-design.md
git commit -m "feat: preflight installer host requirements"
```

### Task 2: Verify venv capability before checkout/setup

**Files:**
- Modify: `install.sh`
- Test: `tests/test_installer_preflight.py`

**Interfaces:**
- Add `verify_venv_support <python-command>` to `install.sh` to create a temporary throwaway venv, verify its Python executable runs, and remove it on both success and failure.
- Call it after `install_dependencies` and before `clone_repository`.

- [ ] **Step 1: Add failing venv capability tests**

Test successful creation and cleanup, failure to create a venv, failure of the created interpreter, and ordering before clone/setup. Assert failures are actionable and temporary directories do not remain.

- [ ] **Step 2: Run focused test to confirm it fails**

Run: `.venv/bin/python -m pytest tests/test_installer_preflight.py -q -o addopts=''`
Expected: FAIL because the venv verification interface is not implemented.

- [ ] **Step 3: Implement and wire venv verification**

Use `python3 -m venv` in a `mktemp` directory and a cleanup trap; do not modify the selected installation directory. Preserve the installed system Python and venv package versions.

- [ ] **Step 4: Run preflight and installer tests**

Run: `.venv/bin/python -m pytest tests/test_installer_preflight.py tests/test_installer_modes.py tests/test_installer_guardrails.py -q -o addopts=''`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add install.sh tests/test_installer_preflight.py
git commit -m "test: verify installer venv before checkout"
```

### Task 3: Documentation and complete verification

**Files:**
- Modify: `install.sh`
- Modify: `installer/README.md`
- Modify: `tests/test_installer_preflight.py` for the test-only OS-release path parameter and any review-exposed regression case.

- [ ] **Step 1: Document checks and limits**

Describe preflight order, Python floor, disk floor, mode-aware GitHub access, and the fact that this does not make all of `setup.sh` idempotent or repair fully offline.

- [ ] **Step 2: Run full verification**

Run the repository's full core tests, the focused installer tests, Black, isort, Flake8, Mypy, Bash syntax checks, and `git diff --check`. Record test-generated files and clean only those produced by these runs.

- [ ] **Step 3: Commit documentation**

```bash
git add installer/README.md
git commit -m "docs: explain installer preflight checks"
```

- [ ] **Step 4: Open the focused PR and run the review loop**

Link #25; report remaining issue scope, exact local/CI checks, and review findings. For each actionable review finding, add or update a regression test, fix it, rerun relevant checks, and request review again. Stop when the PR is clean, all required checks are green, and the review has no unresolved findings; do not merge without separate confirmation.
