# Transactional Release Updater — Task 5 Design

Status: builder-reviewed and approved by the user; implementation plan in
`../plans/2026-10-28-transactional-release-updater.md`.

## Intent and scope

Complete Task 5 of `../plans/2026-10-28-release-lifecycle.md` (#26/#19): replace
in-place Git updates with verified releases, external state preservation, atomic
activation, and recoverable rollback. Keep the existing update API usable.
Do not touch Issue #38 / PR #39, generated OpenHAB output, package updates, or
Task 6's visual version presentation. No tags, releases, or pull requests are published.

## Discovery and approach

The current installer intentionally makes the install root and releases root-owned
and non-service-writable. External config and secrets are root-owned, group-readable
files in a root-owned directory. Therefore the previously planned all-`knxohui`
worker cannot activate a release or migrate settings without weakening this boundary.

Approaches considered:

1. **Unprivileged worker plus privileged helper:** retains the previous worker
   identity, but divides locking, snapshots, promotion, and recovery across processes
   and needs an equally strict privileged protocol.
2. **Fixed privileged coordinator, isolated unprivileged preparation (selected):**
   keeps ownership and the transaction together. Requires a protected coordinator,
   constrained child execution, and explicit validation of every child output.
3. **Service-writable releases/config:** fewer components, but defeats existing
   ownership guardrails and is rejected.

The user authorized proceeding with approach 2's design. The concrete isolation,
request format, and recovery details below are engineering proposals, not earlier
user requirements. This design supersedes the all-unprivileged-worker statement
in the lifecycle spec and plan for Task 5 only; update those documents on approval.

## Goals, constraints, and anti-goals

- Stable is the default. Only explicit `prerelease` selection enables prereleases.
- SHA-256 must match before extraction; activation uses an atomic `current` rename.
- Never execute release Python, pip, migration scripts, hooks, or binaries as root.
- Never import installed application modules into the privileged coordinator.
- Preserve config keys, secrets, sessions, jobs, generated files, backups, and custom
  canonical paths. Never overwrite unrelated runtime data on rollback.
- Fail closed on unsafe ownership, missing isolation support, bad metadata, or
  unsupported migration contracts; no shell/Git/root fallback.
- Linux/systemd is the production target; no additional Python dependency is needed.
- SHA-256 from the same release detects corruption, not compromise of its publisher.
  Artifact signing and dependency lockfiles remain separate future work.

## Components and privilege boundary

### Fixed coordinator

`installer/update_release.py` provides `ReleaseUpdater.run() -> UpdateResult`.
The verified administrator bootstrap installs a standalone, stdlib-only copy at
`/usr/local/libexec/knx_to_openhab/update_release.py`. Its parent chain is root-owned
and not writable by the service user. Any privileged helper modules are installed
alongside it, never imported from `current`, the working directory, or a venv.
Launch with system Python isolated mode, a fixed working directory, a minimal
environment, and no inherited `PYTHONPATH`, Python startup hooks, or credentials.

`knxohui-update.service` is a fixed root-owned oneshot, independent of the UI cgroup.
It uses `UMask=0077`, `NoNewPrivileges=yes`, private temporary storage, and a
filesystem sandbox. Installer-generated drop-ins allow only the validated custom
install/config/state paths needed for writes. It controls named services through
systemd, not arbitrary commands supplied by the request. Never use `ExecStart=+`.

The coordinator and system policy cannot update themselves from a candidate release.
New coordinator/protocol versions require the verified administrator bootstrap.
A release requiring a newer protocol fails clearly before mutation.

### Release compatibility contract (engineering decision)

Add a packaged `installer/update_contract.json`, generated/validated by the release
builder. Protocol 1 declares `updater_protocol`, `config_copy_protocol`, accepted
input schema versions, output schema version, and `runtime_backward_compatible`.
All versions are bounded integers; reject unknown protocols and false/missing
runtime compatibility. The coordinator validates this as data, not imported code.
For protocol 1, only `CONFIG_DIR/config.json` can migrate. `generator.json`, secrets,
sessions, job indexes, and paths metadata are outside its mutation allowlist.

The fixed copied-config invocation is system Python plus candidate
`installer/config_migrations.py --migrate-copy INPUT --output OUTPUT`, executed
inside the isolated child. Both paths are coordinator-selected workspace files.
No snapshot paths or live destinations are accepted. Output must be one bounded
JSON object with the declared integer schema. Protocol 1 permits only additive
defaults and the schema-version change: existing sibling keys/values must remain
deeply equal. Renaming, deleting, or changing existing values requires a future
coordinator protocol installed by the administrator. The migration child gets the
config copy, not `secrets.env`; refuse legacy plaintext/embedded credentials before
copying, rather than passing them to candidate code.

Protocol-1 releases must not perform incompatible startup/on-read migrations of
shared runtime state. Sessions and job records written before commit must remain
readable by the old release. This is a maintainer compatibility guarantee backed
by lifecycle regression tests, not something a manifest flag alone can prove.
Releases needing incompatible persistent-state changes are refused by this updater
and need a separately designed migration/rollback protocol.

### Isolated preparation and migration children

Provision a dedicated `knxohupdate` system identity with no sudo permissions, no
login, and no membership in `knxohui` or `openhab`. Unlike `knxohui`, it cannot use
the application's existing passwordless service/package commands.

The coordinator launches bounded transient systemd child units with fixed argv
(never a shell), this identity, no capabilities, `NoNewPrivileges=yes`,
`ProtectSystem=strict`, `ProtectHome=yes`, private temporary storage, and writable
access only to the transaction workspace or reserved candidate directory. Hide
live config, secrets, runtime data, backups, and coordinator recovery state.
Networking is enabled only for release download and dependency preparation;
migration execution has no network. Custom paths feed validated unit properties,
not concatenated shell commands. Unsupported sandbox properties fail closed.

Children finish and their whole cgroups are stopped before the coordinator reads
outputs or changes ownership. Reject symlinks, hardlinks, special files, unexpected
owners/modes, and escaping paths in preparation output. Traverse using no-follow,
directory-relative operations; do not recursively chown attacker-controlled paths.
Do not trust a child's success marker as proof of a checksum or safe tree.

## Request, status, and compatibility

- The UI atomically publishes a bounded JSON request under `DATA_DIR/update/`:
  `{"format_version": 1, "request_id": "<uuid>", "channel": "stable"}`.
- No URL, destination, executable, environment, migration path, or service name is
  accepted. Reject unknown fields, invalid IDs/channels, symlinks, nonregular files,
  oversized content, and stale/replayed request IDs. Read once through a no-follow
  descriptor and copy validated values into protected transaction state.
- A UI-side submission lock prevents simultaneous publishers from overwriting each
  other. The coordinator claims the request before acknowledging it; submissions
  during an active transaction report busy, not a second successful update.
- Sudoers adds only exact `systemctl start --no-block knxohui-update.service`
  commands for the existing `/bin` and `/usr/bin` compatibility paths. Existing
  named service/package actions remain; no wildcard, shell, Git, or transient-unit
  permission is granted to the Web UI.
- `update.sh` becomes a thin unprivileged submission client using the same path and
  channel validation. It never runs the coordinator directly as root.
- Existing POST calls without a body mean stable. An optional JSON `channel` is
  validated by the API and again by the coordinator; invalid input returns 400,
  busy returns 409, unavailable installation returns an actionable error.
- The API keeps existing response fields and log endpoint. Logs/status live outside
  releases; root creates bounded, sanitized status/log files readable by `knxohui`.
  Do not follow service-controlled log destinations or expose secrets/child output
  without redaction and size bounds. Start acceptance is not update completion.
- Update checks use release metadata, not branch commits, so advertised updates
  match the operation. Keep compatibility version/commit fields; semantic-version
  presentation and UI screenshots belong to Task 6. Update `web_ui/api_schema.json`.
- Flat legacy/development installs do not self-convert: direct users to the verified
  bootstrap to establish protected paths, external credentials, and the worker.

## Transaction

1. Acquire a root-owned host lifecycle lock in `/run/lock`. Installer/setup/repair
   must cooperate with the same lock, so installation and self-update cannot race.
   Recover any incomplete worker transaction before accepting another request.
   Bootstrap/setup/repair must refuse an uncommitted updater journal before
   replacing code, paths, or state, and instruct the administrator to run the
   installed coordinator's fixed offline-recovery mode first. They must not replace
   the coordinator while such a journal exists. A committed journal can be archived;
   unknown journal versions block changes. Installer entry points must pass lock
   ownership explicitly to nested setup calls, not reacquire the same lock.
2. Validate the canonical, root-owned path contract without sourcing shell files;
   validate all ancestors, disjoint external paths, current target, credentials,
   available space, worker protocol, and absence of installer-incomplete state.
3. Fetch bounded GitHub release metadata in the isolated child. Validate it in the
   coordinator: strict SemVer tag, draft/prerelease flags, exact asset names, HTTPS
   GitHub release URLs and approved redirect hosts, timeouts, and size limits.
   Stable uses the latest stable endpoint; explicit prerelease chooses the highest
   supported SemVer prerelease from a paginated, bounded release listing. Missing or
   malformed assets fail clearly. Never automatically downgrade or reinstall an
   equal-precedence version; build metadata does not alter SemVer precedence.
4. Download archive/checksum unprivileged. Freeze output; copy the archive into
   protected state and independently verify SHA-256 against the strictly parsed
   checksum for `knx_to_openhab-<version>.tar.gz`. Preserve the verified archive.
5. Extract unprivileged with bounds on archive size, expanded size, entry count, and
   individual files. Reject absolute/traversal paths, duplicates, links, devices,
   FIFOs, sparse entries, privilege bits, and unexpected top-level layout. Check
   `VERSION` matches the selected tag; validate the tree independently after exit.
6. Reserve a never-existing `releases/<version>` candidate, marked incomplete in
   protected transaction state. Build its venv at its final absolute path in the
   sandbox, avoiding broken pip/gunicorn shebangs after directory relocation.
   Only this unpublished candidate is child-writable. After the child exits, freeze
   and validate it, make it root-owned/non-service-writable, and keep the old release.
   Never reuse an existing version directory or mutate the active environment.
7. Enter maintenance: reject new jobs/settings mutations, drain existing jobs with
   a bounded wait, then stop UI and backup-cleanup writers while recording prior
   states. If quiescence cannot be established, abort before config mutation.
8. Snapshot exactly the affected external settings with bytes, owner, group, mode,
   and absent-file state into protected `CONFIG_DIR/.updater-state/`. Copy inputs
   into an isolated workspace. Run candidate config migrations there unprivileged,
   using a versioned copied-config CLI contract. Only a resulting config JSON object
   is eligible for promotion; secrets and job indexes are unchanged by Task 5.
   Validate schema/version and preserve sibling keys. Never invoke the candidate's
   existing general snapshot-restore CLI as root or accept arbitrary output paths.
9. Atomically write migrated config with original ownership/mode, persist the
   rollback intent, then atomically switch `current` to the frozen candidate.
10. Restart the UI. Require successful systemd notify readiness and a bounded
    application HTTP readiness probe identifying the expected version. Add a small
    non-sensitive health endpoint; use the configured local bind/TLS settings and
    disable environment proxy inheritance. Restore cleanup unit/timer states.
11. Persist committed status durably, then release maintenance and lock. Keep the
    previous release and recovery snapshot; no automatic release pruning in Task 5.

## Failure and interruption recovery

Before mutation, failures leave `current` and external state unchanged. After
mutation, stop new-version writers, restore original config bytes/metadata and the
previous `current` link, then restart/probe the old service and restore prior timer
state. Preserve jobs, sessions, and unrelated runtime changes; never restore a whole
data-directory archive. Report original failure and rollback outcome separately.

Use a root-owned journal recording request, prior target, candidate, exact snapshot
allowlist, service states, and phase. Atomic writes include file and parent-directory
fsync at rollback-critical boundaries. Never recover from manifests or paths under
service-owned data. Failed rollback retains all evidence and blocks further updates.

Add a fixed recovery mode of the installed coordinator, ordered before the UI at
boot, so an interrupted post-migration transaction cannot start an incompatible
code/config pair. Recovery uses the same lock and trusted journal, is idempotent,
does not start a new download, and never guesses if current/journal disagree.
Normal updater operation and pre-UI recovery must not introduce systemd ordering
cycles. Missing prior release or corrupt recovery state requires admin intervention.

The boot unit is a oneshot with `RemainAfterExit=yes`, required and ordered before
the UI, with no `PartOf` or restart propagation from the UI. It runs once per boot,
not on each normal UI restart. Its recovery mode restores files/link and records
`recovered-awaiting-start`, but never starts or probes the UI while it is ordered
before that UI. The UI then starts normally; a failed boot recovery blocks startup.
The update coordinator depends on successful boot recovery and does not restart
that unit while holding the lifecycle lock. In-process rollback during an update
may restart/probe the UI normally. Administrative offline recovery requires UI and
cleanup writers to be stopped and leaves them stopped. Before another transaction,
the coordinator verifies the restored version's readiness. These modes share the
same journal/lock but have distinct, fixed service-control behavior.

Boot recovery also gates the cleanup service and timer using required/ordered
dependencies. Those units must not start on boot after failed recovery, regardless
of the UI's `Wants` relationship.

For same-boot interruption, add a standalone root-installed startup guard to both
launch helpers. It runs as their unprivileged service identity and never takes the
lifecycle lock. Before touching config, the coordinator atomically/fsync writes a
root-owned, service-readable deny gate in `CONFIG_DIR/.updater-startup-gate.json`.
Absent gate means normal startup; malformed, unsafe, or unreadable gate denies it.
During activation, UI startup is allowed only by a gate identifying a coherent
frozen current target and the exact promoted config digest; cleanup stays denied.
The guard verifies these values and does not accept permits from the request/data
directory. After commit, or after restoring a coherent prior pair during rollback,
the coordinator clears the gate durably before restoring normal service states.
Always set deny before rollback mutations. Thus a coordinator crash can leave a
coherent pair startable, but cannot start either half of an interrupted config/link
switch. The guard has no `ExecStart=+`, privileged import, or updater-lock dependency.
Boot recovery reconciles the gate from its protected journal, never vice versa.

Pre-activation failure may remove only a candidate positively identified by the
protected journal as created by this transaction, unpublished, and not the current
or prior target. Stop child cgroups first, validate the root-owned parent, and use
no-follow deletion without crossing mounts. This allows a fresh retry of that
version; never resume or overwrite a partial environment. If ownership/provenance
is ambiguous, retain the candidate and require administrator intervention.

## Repo changes and verification

Expected changes: worker and isolated-child orchestration, update/recovery units,
installer provisioning and repair, standalone submission client, config migration
copy contract, readiness/maintenance API plumbing, updater facade and API schema,
sudoers, documentation, and focused tests. Update permission-repair/uninstall paths
only as necessary to recognize these fixed components and retain recovery data.

Implementation checklist:

- [x] Trace existing paths, ownership, migration, API, launcher, and policy.
- [x] Write this design with explicit engineering decisions.
- [x] Independent builder check; resolve material gaps (final review: no material questions).
- [x] User approval of the reviewed design.
- [x] Write the implementation plan.
- [ ] Write regression tests before product code, following the plan after its review.

Tests must cover default/explicit channel selection and SemVer ordering, bad
metadata/assets/checksum/archive, timeouts/truncation/limits, no-update, request
validation and concurrency, installer/worker locking, sandbox escape attempts,
child cgroup teardown, venv final paths, config sibling preservation, jobs draining,
migration/restart/readiness failure, rollback failure, crash/boot recovery, custom
paths, legacy refusal, API compatibility, and root-import/command-policy boundaries.
Use injected HTTP/systemd adapters for unit tests; exercise real ownership,
filesystem sandboxing, and systemd ordering in an isolated Linux VM/container
where systemd is available, not by modifying the development host.

Run focused tests first, then applicable core/UI tests, Black/isort/flake8, Bash
syntax, systemd unit validation, sudoers validation, and `git diff --check`.
Report unavailable platform checks, never imply mock tests prove real confinement.

Builder discretion: internal module splits, bounded timeout/size defaults with
documented rationale, test fixtures, and status wording. Privilege boundaries,
durable recovery, and compatibility behavior are not discretionary.
