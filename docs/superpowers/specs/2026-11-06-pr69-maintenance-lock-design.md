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

## Design Details

Create a root-owned lock directory under `/run/lock` and a lock file writable
by the `knxohui` group. A small stable helper implements shared acquisition for
service launchers and exclusive acquisition for setup/uninstall. Launchers use
non-blocking shared acquisition, so systemd sees a failed start rather than an
indefinite activation while maintenance is active.

Setup first stops the Web UI and cleanup services, installs the lock-aware
stable launch helpers, then repeatedly waits for updater quiescence, stops the
Web UI again, and attempts an exclusive lock. Once acquired, it rechecks updater
state/jobs and Web UI state/jobs before its first application mutation. If the
exclusive acquisition loses a race to a shared service, it repeats the
quiescence/stop sequence. Setup preserves an already-masked updater unit instead
of replacing its mask with a regular unit file.

Uninstall uses the same lock, performs a final Web UI stop after updater
quiescence, checks states/jobs again, then disables and removes application
files while holding the exclusive lock. Unit-mask symlinks owned by the
administrator are not removed.

## Acceptance Criteria

- A service start attempted during setup/uninstall cannot execute application
  code while files are changing.
- An updater that is active before maintenance completes or setup/uninstall
  fails closed; a queued updater cannot mutate files after exclusive lock
  acquisition.
- The Web UI cannot restart and remain active across setup/uninstall's final
  quiescence check.
- Existing masked unit files remain masks after setup or uninstall.
- A not-found fragment with retained active state or jobs is not treated as
  quiescent.
- Lock timeout, malformed lock path, or systemd inspection failure leaves
  application files untouched.
- Tests cover lock contention, service starts during maintenance, concurrent
  activation/jobs, masked/missing units, and failure cleanup.
