# Setup and Uninstall Maintenance Lock

## Intent

Prevent setup or uninstall from changing application files while the Web UI,
updater, recovery helper, or backup-cleanup service is using them. Preserve
administrator-controlled systemd masks and keep the existing updater lock
contract usable for recovery.

## Approaches

- **Effective systemd masks with snapshot/restore:** block units in systemd
  while preserving existing fragments and masks. This is compatible with old
  launchers, but requires careful handling of unit precedence, first install,
  failures, and setup's own unit replacement.
- **Shared/exclusive maintenance lock (chosen):** stable launch helpers take a
  non-blocking shared lock for the lifetime of their work; setup and uninstall
  stop relevant services and take the exclusive lock through filesystem
  mutations. This avoids relying on systemd path precedence and leaves
  persistent enablement untouched. Setup's recovery helper explicitly runs
  under the already-held maintenance lock and retains its existing updater
  lock check.
- **Only reuse `updater.lock`:** this blocks update transactions but not a Web
  UI or backup-cleanup process, so it does not protect the full mutation
  window.

The shared/exclusive lock is selected because all current release operations
are launched through stable helpers that setup can update, it composes with the
existing updater lock, and it avoids temporary edits to administrator-owned
unit files.

## Goals and Constraints

- Use a stable lock path outside the application and configurable runtime-data
  trees so setup can coordinate before migration and custom-path installs.
- Web UI, updater, backup cleanup, and standalone recovery take a shared lock
  before touching application state and retain it until their work exits.
- Setup and uninstall take an exclusive lock after stopping services and
  confirming active updater work is quiescent; they hold it through mutations.
- Setup and uninstall also hold the existing `DATA_DIR/updater.lock` contract
  through mutations so legacy update/recovery processes that do not yet take the
  maintenance lock cannot overlap file changes.
- Shared-lock acquisition by a service is non-blocking and fails closed while
  maintenance is active. Setup retries stop/quiesce/acquire as needed and has
  a bounded timeout.
- Setup releases the exclusive lock only after all file and unit mutations,
  immediately before restarting the Web UI. Its failure trap releases the lock
  before restoring previously active services.
- Setup does not overwrite an updater unit that systemd reports masked. Uninstall
  preserves administrator mask symlinks.
- A missing unit fragment does not imply an inactive unit: inspect active state
  and queued jobs before proceeding.
- No dependencies, persistent enablement changes, or updater lock semantics are
  introduced.

## Non-Goals

- Prevent root from deliberately bypassing the stable helpers and directly
  modifying installed files.
- Change transactional update locking or release activation behavior.
- Solve the separate custom `EnvironmentFile` propagation finding here; it will
  be handled as its own follow-up after the lock lifecycle is stable.

## Runtime Lock-Path Resolution Follow-Up

Runtime entry points must use one resolver in `maintenance_lock.sh` to read the
persisted lock path without evaluating `paths.env`. A nonempty environment
override must match the persisted value; when no value is persisted, runtime
tools may use only the default lock path. Only setup may explicitly allow a
custom path during initial installation, before it is persisted. Update,
recovery, uninstall, and lock-aware service launchers must all use the resolver.
Malformed lines or assignment names that appear to target the lock-path key
must fail closed rather than silently selecting the default path.
The maintenance helper is selected from the fixed stable libexec location, with
only a fixed package-local fallback for installations predating the stable
helper; an environment variable cannot redirect helper loading.

Approaches considered: a shared resolver function in the already installed
shell helper, a separate Python resolver executable, or duplicating parsing in
each script. The shared shell function is selected because all lock-aware
launchers already source it, it adds no dependency or new executable contract,
and it gives setup a narrow explicit initial-install mode. A standalone Python
tool would add packaging and stable-helper lifecycle; duplicated parsers would
preserve the current divergence.

## Design Details

Create a root-owned lock directory under `/run/lock` and a lock file writable
by the `knxohui` group. A small stable helper implements shared acquisition for
service launchers and exclusive acquisition for setup/uninstall. Launchers use
non-blocking shared acquisition, so systemd sees a failed start rather than an
indefinite activation while maintenance is active.

The lock path must identify a regular file with exactly one hard link. Setup
opens it with `O_NOFOLLOW`, checks the opened inode with `fstat`, then applies
ownership and mode through that descriptor so a configured hard-link alias
cannot change another file's metadata.

Every existing directory from `/` through the lock parent must be root-owned
and not group/other-writable. A root-owned sticky directory is allowed because
sticky semantics protect root-owned descendants. Setup validation, tmpfiles
generation, and every runtime lock acquisition apply this check so a user
cannot rename an ancestor and redirect a later name-based open to another
inode.

The tmpfiles writer must verify that the `knxohui` service group exists even
when the lock parent has not yet been created, so it cannot emit rules that
systemd-tmpfiles cannot apply.

Setup first stops the Web UI and cleanup services, installs the lock-aware
stable launch helpers, then repeatedly waits for updater quiescence, stops the
Web UI again, and attempts an exclusive lock. Once acquired, it rechecks updater
state/jobs and Web UI state/jobs before its first application mutation. If the
exclusive acquisition loses a race to a shared service, it repeats the
quiescence/stop sequence. Setup preserves an already-masked updater unit instead
of replacing its mask with a regular unit file.

For compatibility with older launchers and standalone update scripts, setup
also holds exclusive updater-lock files for both the previously persisted and
the selected runtime-data directories. Uninstall holds the configured runtime
updater lock. A lock-holder process retains these locks through all mutations;
setup's own recovery helper is explicitly told to rely on the already-held
updater lock rather than trying to acquire it again.

Uninstall uses the same lock, performs a final Web UI stop after updater
quiescence, checks states/jobs again, then disables and removes application
files while holding the exclusive lock. Unit-mask symlinks owned by the
administrator are not removed.

On purge, uninstall removes the dedicated default lock parent after deleting
its tmpfiles rule and while the exclusive lock descriptor is still held. This
avoids a release/reacquire race; custom lock parents and non-purge uninstalls
remain untouched. Before any destructive uninstall actions, purge must also
confirm that this default parent is not itself a mountpoint; if the check is
unavailable or inconclusive, uninstall fails closed.

## Acceptance Criteria

- A service start attempted during setup/uninstall cannot execute application
  code while files are changing.
- An updater that is active before maintenance completes or setup/uninstall
  fails closed; a queued updater cannot mutate files after exclusive lock
  acquisition.
- A legacy process holding `updater.lock` completes or causes bounded
  maintenance failure before setup/uninstall mutates application files.
- A lock path beneath a non-root-owned or non-sticky group/other-writable
  ancestor is rejected before setup changes lock metadata or a service opens it.
- Runtime environment overrides that disagree with `paths.env`, or choose an
  unpersisted custom path, fail before acquiring a maintenance lock; setup alone
  can use an initial custom path and persists it before runtime services start.
- Tmpfiles generation rejects a missing `knxohui` group even when the configured
  lock parent does not exist yet.
- The Web UI cannot restart and remain active across setup/uninstall's final
  quiescence check.
- Existing masked unit files remain masks after setup or uninstall.
- Purge removes the default lock parent before deleting the service group, while
  retaining the exclusive lock descriptor; custom lock parents remain intact.
- Purge refuses to remove the default lock parent if it is a mountpoint or its
  mount status cannot be determined, before disabling units or deleting files.
- A not-found fragment with retained active state or jobs is not treated as
  quiescent.
- Lock timeout, malformed lock path, or systemd inspection failure leaves
  application files untouched.
- Tests cover lock contention, service starts during maintenance, concurrent
  activation/jobs, masked/missing units, and failure cleanup.
