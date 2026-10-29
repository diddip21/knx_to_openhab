# Transactional Release Updater Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver Task 5 (#26/#19): verified, isolated release preparation with protected activation, rollback, and interruption recovery.

**Architecture:** A fixed root-installed stdlib coordinator owns the transaction and journal. Transient systemd children run as `knxohupdate` without sudo or live-state access. Root-owned startup gates and boot recovery prevent incompatible code/config pairs from starting.

**Tech Stack:** Python 3.12+, Bash, systemd, stdlib HTTP/JSON/tar/hashlib, Flask, pytest.

**Status (2026-10-30):** Tasks 1–8 implemented and independently task-reviewed.
Task 9 assembled regressions/harness are implemented; independent Task-9 and
whole-branch review remain pending. Parent lifecycle Task 5 stays incomplete:
disposable real-systemd boot/confinement/cgroup/resource-failure acceptance is
**NOT VERIFIED**. See `../../../tests/integration/README.md` for exact boundaries
and opt-in prerequisites. A systemd-enabled development WSL host is not disposable.
Historical unchecked step boxes below are not claims of missing source; this status
and the task reports distinguish implementation from outstanding acceptance/review.

**Spec:** `docs/superpowers/specs/2026-10-28-transactional-release-updater-design.md` (approved by user).

## Global Constraints

- Stable is the default. Only explicit `prerelease` selection enables prereleases.
- SHA-256 must match before extraction; activation uses an atomic `current` rename.
- Never execute release Python, pip, migration scripts, hooks, or binaries as root.
- Never import installed application modules into the privileged coordinator.
- Preserve config keys, secrets, sessions, jobs, generated files, backups, and custom canonical paths. Never overwrite unrelated runtime data on rollback.
- Fail closed on unsafe ownership, missing isolation support, bad metadata, or unsupported migration contracts; no shell/Git/root fallback.
- Linux/systemd is the production target; no additional Python dependency is needed.
- Coordinator/policy upgrades require the verified administrator bootstrap.
- Only `CONFIG_DIR/config.json` may migrate in protocol 1, additively; no generator/secret/job-index migrations.
- No Issue #38 / PR #39, generated-output changes, release publication, or Task 6 visual changes.

## Review Focus

- Same-boot crashes between config/link writes: UI and cleanup must not start a mixed pair (Tasks 3, 6).
- Candidate children leave forked writers or symlink/hardlink trees: stop entire cgroups before inspection; reject unsafe output (Tasks 2, 4).
- Custom paths contain spaces, percent signs, or newlines: preserve legitimate paths, encode systemd values, reject unrepresentable paths without writes (Tasks 1, 7).
- UI crashes after publishing but before acknowledgment: no overwritten request, duplicate start, or permanently busy client (Task 8).
- A failed candidate writes shared sessions/jobs before readiness: prior release must still read them; unsupported runtime migrations are refused (Tasks 1, 9).

## Module map and execution rules

New trusted code lives in `installer/update_core/`: `protocol.py` (pure data contracts),
`secure_fs.py` (no-follow operations), `state.py` (journal/lock/gate),
`systemd.py` (fixed service operations and sandboxes), `artifacts.py` (release data
validation), and `transaction.py` (state machine). `installer/update_release.py`
is the installed coordinator CLI; `installer/update_prepare.py` is the fixed
unprivileged child CLI; `installer/update_start_guard.py` is the unprivileged
launcher guard; `installer/update_submit.py` is the shared unprivileged submission CLI.
Create `installer/update_core/__init__.py` with no side effects.

The installer copies this whole trusted bundle to root-owned libexec. The CLI
bootstraps only its validated root-owned sibling package under Python `-I`, not
repo/application/venv imports. Pure protocol functions can also be imported from
the repository by the Web UI; that does not confer privileged execution.

Types shared below: `Paths`, `UpdateRequest`, `ReleaseInfo`, `ReleaseContract`,
`Journal`, `ServiceState`, `UpdateResult`, and `Limits` are frozen dataclasses or
strictly validated serialized forms defined in `protocol.py`. `Paths` mirrors the
existing canonical environment contract without importing `knxoh_paths` at root.
Keep its compatibility pinned with tests against `knxoh_paths.get_paths()`.

Before execution, use the worktree skill to verify isolation; do not discard any
existing changes. Each task follows red/green tests and a focused commit. Later
tasks consume earlier interfaces, not duplicate implementations. Do not mark the
parent lifecycle Task 5 complete until Task 9 passes or explicitly reports blockers.

### Task 1: Define pure release and copied-config contracts

**Files:** Create `installer/update_core/{__init__,protocol,artifacts}.py`,
`installer/update_contract.json`, `tests/test_update_protocol.py`;
modify `installer/config_migrations.py`, `scripts/build_release.py`,
`tests/test_config_migrations.py`, `tests/test_release_artifacts.py`.

**Interfaces:** `parse_request(raw: bytes) -> UpdateRequest`;
`parse_contract(raw: bytes) -> ReleaseContract`;
`select_release(metadata: object, channel: str, current: str) -> ReleaseInfo | None`;
`validate_config_copy(original: dict, migrated: dict, contract: ReleaseContract) -> None`;
`migrate_copy(source: Path, output: Path) -> int`.

- [ ] Write failing tests: request accepts exactly format/version UUID/channel; reject unknown fields/bools/oversize; strict SemVer sorting including `rc.10 > rc.2`, build metadata equality, no downgrade; stable excludes drafts/prereleases; prerelease pagination bound; missing/duplicate assets and unsafe URLs fail. Assert migrated sibling trees equal originals except `schema_version`; changing `general` values raises. Assert copied migration leaves input bytes unchanged and never writes live paths.
- [ ] Run `python -m pytest -q tests/test_update_protocol.py tests/test_config_migrations.py tests/test_release_artifacts.py`; record failures for missing interfaces.
- [ ] Implement interfaces and `--migrate-copy INPUT --output OUTPUT` as mutually exclusive with the existing restore CLI. Package protocol-1 manifest with current schema, accepted input schemas, and explicit backward compatibility. Builder validates manifest against source schema without importing candidate code in the updater. Use limits: request 4 KiB, config/metadata 1 MiB each, 10 metadata pages, 30-second HTTP operations. Document constants in `Limits`.
- [ ] Run the same focused command; expect all pass, including old artifact/migration tests.
- [ ] Commit only these paths: `feat: define release updater compatibility contracts`.

### Task 2: Implement protected filesystem primitives

**Files:** Create `installer/update_core/secure_fs.py`, `tests/test_update_secure_fs.py`.

**Interfaces:** `read_regular(path: Path, max_bytes: int) -> bytes`;
`atomic_write(path: Path, data: bytes, uid: int, gid: int, mode: int) -> None`;
`freeze_tree(root: Path, expected_uid: int) -> None`;
`remove_candidate(paths: Paths, journal: Journal) -> None`.

- [ ] Write failing POSIX tests for descriptor-relative no-follow reads/writes, symlink ancestors, multiple hardlinks, raced directory entries, special files, mount boundaries, owner/group/mode preservation, short writes, file/parent fsync, and deletion refusing current/prior/unrecorded candidates. Assert ordinary unrelated files survive every rejected operation.
- [ ] Run `python -m pytest -q tests/test_update_secure_fs.py`; expect missing-module failures.
- [ ] Implement operations using directory FDs, `O_NOFOLLOW`, `fstat`, exclusive temporary names, and same-directory replacement. Inspect complete child output only after cgroup teardown. Reject untrusted links, writable ancestors, set-ID bits, unsafe owners, and different devices; never follow links during cleanup or ownership changes. Restrict destructive work to a journal-owned unpublished candidate.
- [ ] Run focused tests on Linux and Windows; explicitly skip POSIX-only guarantees on Windows, not simulate their success.
- [ ] Commit: `feat: add protected updater filesystem operations`.

### Task 3: Implement journal, lifecycle lock, and startup gate

**Files:** Create `installer/update_core/state.py`, `installer/update_start_guard.py`,
`tests/test_update_state.py`, `tests/test_update_start_guard.py`.

**Interfaces:** `LifecycleLock.acquire() -> ContextManager[None]`;
`StateStore.load() -> Journal | None`, `StateStore.save(journal: Journal) -> None`;
`StateStore.snapshot_config() -> None`, `StateStore.restore_config() -> None`;
`write_gate(paths: Paths, mode: str, target: Path | None, config_digest: str | None) -> None`;
`check_start_allowed(paths: Paths, role: str) -> bool` (`ui` or `cleanup`).

- [ ] Write failing tests for exclusive host lock, unsafe lock file, corrupt/future journals, config snapshots retaining uid/gid/mode/absent state, replay IDs, and journal path allowlists. Assert deny gate blocks both roles; permit matching target/config allows UI only; stale digest, swapped current, unreadable or malformed gate denies. Assert guard never takes lifecycle lock.
- [ ] Run `python -m pytest -q tests/test_update_state.py tests/test_update_start_guard.py`; expect failure.
- [ ] Implement root-owned `/run/lock/knxohui-lifecycle.lock` and protected `CONFIG_DIR/.updater-state/` journal/snapshots/status. Use explicit phases: `claimed`, `preparing`, `prepared`, `quiescing`, `snapshotted`, `config-written`, `activated`, `checking`, `committed`, `rolling-back`, `recovered-awaiting-start`, `rolled-back`, `recovery-failed`. Persist intent before each mutation and gate deny before config/link changes. Journal owns exact prior/candidate paths and service states; unknown states block recovery.
- [ ] Run the focused command; expect pass, including failure injection before/after every durable write.
- [ ] Commit: `feat: add durable update journal and startup gates`.

### Task 4: Build isolated systemd preparation and artifact handling

**Files:** Create `installer/update_core/systemd.py`, `installer/update_prepare.py`,
`tests/test_update_sandbox.py`, `tests/test_update_artifacts.py`; extend `artifacts.py`.

**Interfaces:** `SystemdAdapter.run_child(stage: str, paths: Paths, workspace: Path, candidate: Path | None) -> None`;
`SystemdAdapter.stop_children(request_id: str) -> None`;
`SystemdAdapter.capture_services() -> ServiceState`;
`verify_archive(archive: Path, checksum: bytes, release: ReleaseInfo) -> None`;
`validate_extracted_tree(root: Path, release: ReleaseInfo) -> ReleaseContract`.

- [ ] Write failing tests for fixed argv/user/properties, no shell or sudo in children, network disabled during migration, hidden live paths, failure on unsupported sandbox properties, timeout/forked descendant teardown, URL redirect host validation, corrupt/truncated checksum/archive, traversal/duplicate/sparse/link/device entries, expansion limits, and final-path venv scripts.
- [ ] Run `python -m pytest -q tests/test_update_sandbox.py tests/test_update_artifacts.py`; expect failure.
- [ ] Implement stages `metadata`, `download`, `extract`, `dependencies`, `migrate`. Root independently validates frozen metadata/archive/tree after stopping all descendants. Approved HTTPS hosts are `api.github.com`, `github.com`, `release-assets.githubusercontent.com`, and `objects.githubusercontent.com`; redirects stay on this set and asset URLs match this repository/tag. Limit compressed archive to 128 MiB, expanded files to 512 MiB, 20,000 entries, and 64 MiB/file; dependency stage timeout 15 minutes. Reserve final candidate before creating venv with `--copies`; normalize only the known venv `lib64 -> lib` alias inside the sandbox, rejecting all remaining links. Never execute that venv at root. Allowlist fixed child operations, not request-specified commands.
- [ ] Run focused tests; verify root does not trust child success alone and cannot read/write child-controlled output before teardown.
- [ ] Commit: `feat: isolate release download and preparation`.

### Task 5: Add cross-worker maintenance and readiness

**Files:** Create `web_ui/backend/update_maintenance.py`, `tests/test_update_maintenance.py`;
modify `web_ui/backend/{app,jobs}.py`, `web_ui/api_schema.json`.

**Interfaces:** `mutation_lease(paths: InstallPaths) -> ContextManager[None]`;
`maintenance_requested(paths: InstallPaths) -> bool`;
`wait_for_quiescence(paths: Paths, timeout: float, *, request_id=None)` returns an
already-acquired quiescence context handle, held through commit/rollback;
GET `/api/health` returns only `{"status": "ready", "version": "<VERSION>"}`.

- [ ] Write failing tests that maintenance blocks new queued/running jobs, config writes, deploy/rollback/delete/service mutations across two processes, while read-only status/log/health remains available. Existing queued/running work drains; active mutation leases prevent coordinator proceeding. Health works without creating a session and reveals no paths/secrets; recovery/version mismatch is not ready.
- [ ] Run `python -m pytest -q tests/test_update_maintenance.py tests/test_web_ui_job_endpoints.py`; expect new tests to fail.
- [ ] Implement root-owned maintenance intent plus shared/exclusive mutation leases whose paths/inodes are provisioned by installer, not replaceable via service-owned directories. Job leases span queue submission through completion, including exception paths. Acquire exclusive lease before stopping writers; hold it through migration/commit/rollback. Bound drain to 120 seconds; timeout removes maintenance without killing jobs. Add health to the auth exemption before session initialization, with version read from active source `VERSION` only. No visual UI changes.
- [ ] Run focused tests and affected auth/session/API-schema tests; expect pass without weakening mutation authentication/CSRF.
- [ ] Commit: `feat: quiesce application writes for release updates`.

### Task 6: Implement transactional coordinator and recovery

**Files:** Create `installer/update_core/transaction.py`, `installer/update_release.py`,
`tests/test_release_updater.py`, `tests/test_update_recovery.py`.

**Interfaces:** `ReleaseUpdater(paths: Paths, systemd: SystemdAdapter, limits: Limits).run() -> UpdateResult`;
`ReleaseUpdater.recover(mode: str) -> UpdateResult` (`boot` or `offline`);
`UpdateResult` exposes `status`, `version`, `error`, `rollback_status`, and `request_id`.
CLI modes: `--run`, `--recover-boot`, `--recover-offline`, `--check-clean-state`.

- [ ] Write failing adapter-based tests for the spec's full phase sequence, success/no-update/busy, credential and path preflight, insufficient space, unsupported contract, active jobs timeout, migration failure, restart failure, wrong-version/readiness timeout, config/link rollback, and failed rollback blocking future requests. Parameterize simulated crash/restart at every journal/mutation boundary, including coherent startup gate permits.
- [ ] Run `python -m pytest -q tests/test_release_updater.py tests/test_update_recovery.py`; expect failure.
- [ ] Implement state machine using Tasks 1–5. Root preflight reads only trusted path environment; no application imports or candidate executables. HTTP readiness uses the deployed direct Gunicorn HTTP bind/port, no proxy environment or redirects; wildcard binds map to loopback. Public reverse-proxy HTTPS/unrelated TLS keys are not readiness; direct/custom TLS is not claimed. Wait at most 60 seconds for systemd notify plus expected-version health. Before commit keep cleanup denied; mark committed, clear gate, then restore cleanup state. Boot/offline recovery restores but never starts UI. Unknown journals/targets require admin intervention; retain evidence on failure. Reserve/free only this transaction's candidate; retain previous releases and snapshots.
- [ ] Run focused tests plus all `tests/test_update_*.py`; expect pass with separate original/rollback errors and byte-identical unrelated runtime data.
- [ ] Commit: `feat: implement transactional release activation and rollback`.

### Task 7: Provision protected services and lifecycle coordination

**Files:** Create `installer/knxohui-update.service`, `installer/knxohui-update-recovery.service`;
modify `installer/{setup.sh,knxohui.sudoers,knxohui.service,knxohui-backup-cleanup.service,knxohui-backup-cleanup.timer,launch_web.sh,launch_backup_cleanup.sh}`,
`install.sh`, `fix_permissions.sh`, `uninstall.sh`, `installer/uninstall.py`;
extend `tests/test_{privilege_policy,installer_lifecycle,installer_guardrails}.py`;
create `tests/test_update_units.py`.

**Interfaces:** setup provisions protected libexec bundle, `knxohupdate` identity,
trusted unit drop-ins, fixed lock/lease/status files, recovery dependencies, and
minimal sudoers start rule. Startup guard CLI takes only `--role ui|cleanup`.

- [ ] Write failing tests for protected package/import chain, no candidate pip/Python at root in updater units, exact sudo rule, non-sudo child identity, custom path escaping, installer refusing pending/future journal before writes, inherited verified lifecycle lock ownership, once-per-boot recovery ordering, and both launchers invoking fixed guard. Pin recovery `RemainAfterExit=yes`, no `PartOf`, and no UI-start action in recovery. Ensure repair does not replace coordinator with unresolved state and ordinary uninstall preserves recovery evidence.
- [ ] Run `python -m pytest -q tests/test_update_units.py tests/test_privilege_policy.py tests/test_installer_lifecycle.py tests/test_installer_guardrails.py`; expect new assertions to fail.
- [ ] Implement install/repair provisioning without loosening existing root ownership. Use generated drop-ins with encoded systemd paths, rejecting newline/NUL paths. `Requires`/`After` recovery apply to UI, cleanup service/timer, and updater. Recovery has no dependency back to those writers. Only verified bootstrap may replace trusted code/policy. Root owns lifecycle lock; nested installer passes a live inherited lock descriptor validated with ownership/inode checks, never a user-controlled boolean bypass. Pending journals fail before code/path changes; plan/cancel remain read-only.
- [ ] Run focused tests, Bash syntax checks, `systemd-analyze verify` and `visudo -cf` where available; record unavailable commands. Test unit graph in the isolated systemd harness in Task 9.
- [ ] Commit: `feat: provision protected release updater services`.

### Task 8: Connect submission, API checks, logs, and compatibility wrapper

**Files:** Create `installer/update_submit.py`, `tests/test_update_submission.py`;
modify `web_ui/backend/{updater,app}.py`, `web_ui/api_schema.json`, `update.sh`,
`tests/test_updater.py`, relevant API endpoint tests, `installer/README.md`, `web_ui/README.md`.

**Interfaces:** `submit_update(paths: Paths, channel: str = "stable") -> UpdateResult`;
`Updater.trigger_update(channel: str = "stable") -> tuple[bool, str]` retains old call form;
release-based `Updater.check_for_updates(channel: str = "stable") -> dict`;
`Updater.get_update_log() -> str` retains response contract.

- [ ] Write failing tests for bodyless stable POST, explicit prerelease, bad content/unknown fields/channel (400), busy (409), no coordinator/legacy layout (actionable error), fixed nonblocking systemctl argv, atomic no-follow request publication, replay/stale status, and failure/crash before/after claim. Assert old response fields remain, no UI chmod/Popen of `update.sh`, no branch-commit comparison, bounded safe logs, and no Git mutation anywhere in wrapper.
- [ ] Run `python -m pytest -q tests/test_update_submission.py tests/test_updater.py` plus affected endpoint tests; expect failures against legacy trigger behavior.
- [ ] Implement submission lock and protected acknowledgment: root status records claimed request ID; unclaimed request can be replaced only under submit lock after confirmed inactive worker and a bounded 30-second acknowledgment timeout, never during an active operation. Busy status is request-specific. Requests have only the three specified fields. Wrapper invokes the shared unprivileged CLI with default stable or explicit `--channel`; API uses authenticated existing route, surfaces busy distinctly, and keeps Windows simulation without bypassing validation. Advertise release updates with honest compatibility fields (`unknown` commit where artifact lacks metadata), never pretend version strings are commit hashes. Document one-time verified-bootstrap recovery/setup requirements and async completion semantics.
- [ ] Run focused tests plus API-schema/auth tests; expect pass for existing no-argument clients and channel failures.
- [ ] Commit: `feat: submit verified release updates from the web API`.

### Task 9: Verify assembled lifecycle and synchronize parent documents

**Files:** Create `tests/integration/test_update_transaction.py` and an isolated systemd
harness under `tests/integration/`; modify `docs/superpowers/plans/2026-10-28-release-lifecycle.md`,
`docs/superpowers/specs/2026-10-28-safe-install-lifecycle-design.md`, approved Task-5
spec/checklist, and integration test documentation. Do not expand into parent Task 7's CI work.

**Interfaces:** fixtures use disposable paths, fake release HTTP/systemd adapters for
ordinary integration tests, and an explicitly opted-in disposable Linux systemd
VM/container for real sandbox/ownership/ordering tests. Never provision the host.

**Task-9 handoff:** 11 assembled lifecycle tests pass with real protected files,
demoted stage/application processes and local HTTP; service-manager/notify/cgroup
effects are explicitly fake. Three guarded real-systemd acceptance tests are
implemented but skipped: a disposable guest/provider is unavailable, and WSL is
rejected. Isolated-Python migration imports and pre-pip venv alias normalization
were fixed after captured assembled failures. Queued-Future cancellation is now
explicitly covered. Final local core: root 1265 passed/18 skipped, non-root 753
passed/530 skipped; actual-app Chromium update tests 18 passed. Full source-snapshot
Black/isort/flake8, Bash, static-unit and sudoers validation passed. These checks
do not establish real-manager acceptance. See `../../../tests/integration/README.md` for evidence limits,
root-private pytest temp requirements and exact opt-in prerequisites. Keep the
combined run/review/completion boxes below open until the missing real acceptance
and independent Task-9/whole-branch review are supplied.

- [ ] Write regression scenarios: stable/default and explicit prerelease success; already current; bad artifact; failed migration/readiness with old app serving after rollback; custom paths; concurrent installer/update; kill during config/link switch; reboot recovery blocks both writers on corrupt journal; same-boot guard; real child cannot access config/secrets/runtime or sudo and cannot leave a writer descendant. Launch candidate with existing sessions/job index, then rollback and assert prior release reads both. Fail dependency install once, retry same version from a clean candidate, and preserve unrelated sentinel files.
- [ ] Run `python -m pytest -q tests/integration/test_update_transaction.py -o addopts=` and the documented opt-in systemd suite; capture failed assembled paths before fixing integration defects.
- [ ] Resolve integration defects without weakening boundaries; update approved design status and parent Task-5 architecture/interfaces, keeping other tasks intact. Record which assertions are mock-only versus exercised with real systemd. Request independent whole-branch review before marking Task 5 done.
- [ ] Run `python -m black --check .`, `python -m isort --check-only .`, `python -m flake8 .`, core `python -m pytest -q --ignore=tests/ui` (root-private base when root), relevant `tests/ui/test_update_system.py` against a running app, shell/unit/sudoers validators, and `git diff --check`. Report platform skips/failures explicitly; no screenshots unless UI appearance actually changes (then commit real-state screenshots per AGENTS.md).
- [ ] Commit reviewed integration/docs: `test: verify transactional updater recovery and isolation`. Mark parent Task 5 complete only with evidence; do not claim the full feature commit or verification before it exists.

## Self-review / handoff

- [x] Spec coverage: contracts (1), secure output handling (2), journal/gate (3),
  sandbox/artifacts (4), maintenance/readiness (5), transaction/recovery (6),
  installer/policy/units (7), API/submission (8), real lifecycle verification (9).
- [x] Interface names/types are shared above; no arbitrary child paths/commands are
  accepted from requests, and trusted coordinator imports are explicit.
- [x] Five review-focus conditions each have tests assigned to their owning tasks.
- [x] Tasks are dependent deliverables, not independently shippable unrelated projects.
- [ ] User plan review and execution-method selection.

Recommended execution: subagent-driven with independent security-focused reviews
at each task boundary, because filesystem/sandbox/recovery mistakes can affect
privileged state. Native execution remains possible with whole-branch review.
