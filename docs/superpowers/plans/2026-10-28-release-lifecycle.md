# Release-Based Install and Update Lifecycle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete Issues #30, #24, #27, #25, #26, #19, and #31 with versioned, checksum-verified releases and tested rollback.

**Architecture:** Add a SemVer source and tag-driven release artifacts first. Adapt install paths to immutable `releases/<version>` directories plus atomic `current`; version external configuration migrations and snapshot state before mutation. Make installation repeatable. Run updater work in a dedicated systemd unit as `knxohui`, so it can restart the UI while remaining unprivileged; only exact systemd commands are sudoable. Test the complete lifecycle in an isolated Linux integration harness.

**Tech Stack:** Python 3.12+, Bash, GNU tar, systemd, GitHub Actions, pytest.

**Spec:** `docs/superpowers/specs/2026-10-28-safe-install-lifecycle-design.md`

## Global Constraints

- SemVer tags use `v<version>`; stable is the default update channel; beta/rc are explicitly selected prerelease channels.
- Release code is immutable under `releases/<version>`; `current` switches atomically; user config/data/backups stay outside releases.
- Every downloaded archive must pass SHA-256 verification and safe extraction before activation.
- Migrations are idempotent, versioned, backed up, and recoverable; no user data is stored in a Git checkout/release.
- Update worker runs as `knxohui`; sudoers grants only named service actions, never Git wildcards or shells.
- Retain existing API fields and existing path environment keys for compatibility.

## Review Focus

- No stable release or malformed release metadata: installer/update fail clearly without replacing the active release; test API errors and missing assets.
- Checksum mismatch, traversal archive, or truncated download: reject before activation and preserve current; test all three corrupt artifact cases.
- Concurrent update request: second worker exits without affecting first; test the lock.
- Migration exception or failed health check: restore config snapshot and prior `current`; test both rollback boundaries.
- Custom install/config/data/backup paths and legacy flat install: preserve data and use canonical paths; test custom paths and upgrade migration.

---

### Task 1: Define release version and reproducible artifacts (#30)

**Files:**
- Create: `VERSION`
- Create: `CHANGELOG.md`
- Create: `scripts/build_release.py`
- Create: `.github/workflows/release.yml`
- Create: `tests/test_release_artifacts.py`
- Modify: `installer/README.md`

**Interfaces:**
- `scripts/build_release.py --version VERSION --output-dir DIR` produces a versioned source `.tar.gz` and `.sha256` file, excluding runtime/config/test artifacts.

- [x] Test SemVer/tag validation, deterministic archive contents, exclusions, and checksum output.
- [x] Run `python -m pytest -q tests/test_release_artifacts.py`; observe failures for missing release tooling.
- [x] Implement the version source, initial changelog, artifact builder, and tag-triggered stable/prerelease workflow.
- [x] Run artifact tests twice and verify byte-identical output and a matching SHA-256 digest.
- [ ] Commit: `feat: add semantic release artifacts`.

### Task 2: Make paths and services release-layout aware (#24)

**Files:**
- Modify: `installer/setup.sh`
- Modify: `installer/launch_web.sh`
- Modify: `installer/launch_backup_cleanup.sh`
- Modify: `knxoh_paths.py`
- Modify: `tests/test_knxoh_paths.py`
- Modify: `tests/test_installer_guardrails.py`
- Update: `installer/README.md`, `docs/PRODUCTION_GUIDE.md`, `docs/DEVELOPER_GUIDE.md`

- [x] Add tests for `current -> releases/<version>`, legacy flat fallback, custom `KNXOH_INSTALL_DIR`, and path values that must remain outside releases.
- [x] Run the focused tests and observe the current release layout is unsupported.
- [x] Install application code into a version-named release, atomically publish `current`, and keep the existing environment-file contract.
- [x] Test launch scripts against both new-layout and legacy-layout paths; run Bash syntax checks.
- [x] Commit: `feat: install immutable versioned releases`.

### Task 3: Add schema-versioned, snapshot-backed migrations (#27)

**Files:**
- Create: `installer/config_migrations.py`
- Modify: `installer/migrate_runtime_data.py`
- Modify: `installer/setup.sh`
- Test: `tests/test_config_migrations.py`
- Test: `tests/test_runtime_data_migration.py`

**Interfaces:**
- `migrate_config(config_path: Path, backup_dir: Path) -> int` performs ordered, idempotent migrations and returns the resulting schema version.
- Snapshot only the external config/secrets and rewritten job index before mutation; do not copy or overwrite unrelated user data.

- [x] Test migration from the unversioned legacy schema, idempotent repeat, snapshot contents, invalid future schema, and injected failure restoring original bytes.
- [x] Run the tests and observe failures before implementing the migration functions.
- [x] Implement atomic migration and rollback; retain existing path/data migration ordering and preserve all old sources until path publication succeeds.
- [x] Run migration/path tests on a POSIX runner; on Windows, report permission/symlink cases separately.
- [x] Commit: `feat: add recoverable config migrations`.

### Task 4: Make installer repeatable and release-aware (#25)

**Files:**
- Modify: `install.sh`, `installer/setup.sh`
- Modify: `installer/config_migrations.py`, `installer/migrate_runtime_data.py`
- Modify: `installer/README.md`, `web_ui/README.md`
- Test: `tests/test_installer_lifecycle.py`, `tests/test_installer_guardrails.py`
- Test: `tests/test_config_migrations.py`, `tests/test_runtime_data_migration.py`, `tests/test_privilege_policy.py`

- [x] Add tests for fresh install planning, existing install choices (update/repair/reinstall/cancel), interrupted installation repair, and non-interactive refusal before writes.
- [x] Run the tests and observe existing in-place Git update behavior violates the new contract.
- [x] Replace in-place branch pulls with stable artifact selection; preserve user configuration and only repair missing system components on repair.
- [x] Run installer lifecycle tests and Bash syntax validation; document platform-specific full-suite failures.
- [x] Commit: `fix: make release installation idempotent`.

### Task 5: Implement transactional release updater and finish privilege policy (#26/#19)

**Approved architecture amendment:** The all-`knxohui` worker below is superseded
by a fixed root-owned coordinator with isolated `knxohupdate` preparation children.
Root-owned releases/config remain protected. Use the approved detailed spec
`../specs/2026-10-28-transactional-release-updater-design.md` and implementation
plan `2026-10-28-transactional-release-updater.md`. Implementation Tasks 1–8 are
independently reviewed; assembled Task 9 and whole-branch reviews are pending.
**Task 5 remains incomplete:** real disposable-systemd boot/confinement/cgroup
acceptance is NOT VERIFIED. See `../../../tests/integration/README.md` for the
evidence boundary, guarded harness, and unavailable disposable-guest prerequisites.

**Files:**
- Create: `installer/update_release.py`
- Create: `installer/knxohui-update.service`
- Modify: `update.sh`
- Modify: `installer/setup.sh`
- Modify: `installer/knxohui.sudoers`
- Modify: `web_ui/backend/updater.py`
- Test: `tests/test_release_updater.py`
- Test: `tests/test_privilege_policy.py`
- Test: `tests/test_updater.py`

**Interfaces:**
- `ReleaseUpdater.run() -> UpdateResult` owns lock, stable/prerelease lookup, download/checksum, archive validation, per-release environment, migration snapshot, atomic activation, restart/health check, and rollback.
- Web UI/CLI publish the bounded UUID/channel request and start only fixed
  `knxohui-update.service`; matching protected request-ID claim means submitted,
  not completed. The protected root coordinator survives UI restart; transient
  `knxohupdate` children execute preparation/migration without sudo/live-state access.
- Maintenance holds an exclusive lease through commit/rollback; fixed boot recovery
  gates UI/cleanup, and lock-free startup guards cover same-boot interrupted switches.
- The browser uses its invocation generation plus protected request ID, and reloads
  only for a matching committed projection. HTTP readiness probes direct Gunicorn
  bind/port, not reverse-proxy TLS. Shared jobs/sessions remain backward-readable.

- [ ] Test normal update, already-current, concurrent lock, download/checksum/extraction failures, migration failure, restart failure, health failure, successful rollback, and success.
- [ ] Run updater and privilege-policy tests; observe failures before implementation.
- [x] Implement the coordinator/isolated children, root-owned fixed units, exact sudoers starts, and unprivileged shell client; remove Git fetch/stash/pull/reset update behavior.
- [ ] Verify every failure leaves the old release active and that sudoers has no Git, shell, or wildcard grant.
- [ ] Commit: `feat: add transactional release updater`.

### Task 6: Expose semantic versions in the CLI and Web UI (#30)

**Files:**
- Create: `version.py`
- Modify: `knxproject_to_openhab.py`
- Modify: `web_ui/backend/updater.py`
- Modify: `web_ui/backend/app.py`
- Modify: `web_ui/templates/index.html`
- Modify: `web_ui/static/app.js`
- Test: `tests/test_version_info.py`
- Test: `tests/ui/test_update_system.py`

- [ ] Test CLI `--version`, `/api/version`, stable/prerelease display, and compatibility fields for the old UI.
- [ ] Run focused tests and observe the current UI has commit-only version fields.
- [ ] Implement semantic version display and update dialog while preserving commit metadata and accessible status text.
- [ ] Run API tests and relevant UI tests; save required screenshot evidence only if UI appearance changes materially.
- [ ] Commit: `feat: display semantic application versions`.

### Task 7: Exercise the complete lifecycle in CI (#31)

**Files:**
- Create: `tests/integration/test_release_lifecycle.py`
- Modify: `.github/workflows/ci.yml`
- Modify: `tests/integration/README.md` (create if absent)

- [ ] Add isolated end-to-end scenarios for fresh install, repeat/repair, stable update, no update, custom config, failed download, failed migration, health-check rollback, safe uninstall, and confirmed purge.
- [ ] Run the integration tests against the existing installer and confirm the missing paths fail.
- [ ] Implement fake systemd/sudo/HTTP services and temporary path overrides; never require root or alter the host.
- [ ] Run Linux CI-equivalent integration tests plus the core suite.
- [ ] Commit: `test: cover release install update and rollback lifecycle`.

---
