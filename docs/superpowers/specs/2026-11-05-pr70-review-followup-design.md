# PR #70 Review Follow-up Design

## Intent

Address the two new review findings on PR #70: accept numeric-string Web UI ports in the updater health probe, and recover an interrupted release activation before the Web UI launches after reboot.

## Goals and non-goals

- Normalize integer and decimal-string ports consistently, while rejecting booleans, floats, malformed values, and ports outside `1..65535`.
- Before launching the Web UI, detect an active release marker. If the updater lock is free, restore the recorded previous release (or the legacy install) atomically. If the lock is held, leave the candidate selected so the active updater can finish its health check.
- Fail closed on an unreadable marker, unsafe/missing rollback target, or lock-path error; do not silently launch an unvalidated candidate when safe recovery cannot be established.
- Require the updated stable launcher to be installed before allowing another Web UI update, using a launcher capability marker and the existing setup instruction path.
- Keep the existing release marker format, systemd service model, CLI behavior, and successful update flow compatible.
- No new dependencies, background recovery service, or changes to update success semantics.

## Approaches considered

1. **Recover in the stable Web UI launcher (selected).** Use the existing `updater.lock` to distinguish an in-flight update from a stale marker at boot. This reuses the installed launcher and update lock, needs no new systemd unit, and can roll back before Gunicorn starts.
2. **Add a separate boot-time recovery systemd unit.** This makes the ordering explicit but adds a unit, setup/migration state, and another recovery entry point. It is more machinery than needed for a pointer rollback.

The selected approach is the smallest one that preserves normal health validation while recovering a marker orphaned by process or power loss. The existing Web UI setup preflight will require the capability-marked launcher, prompting a one-time `setup.sh` run on installations that still have an older root-installed launcher.

## Behavior

The health endpoint resolver accepts an integer or an ASCII decimal string, converts once to an integer, then applies the existing range check. Other input types are rejected instead of being truncated or treated as booleans.

At Web UI startup, the stable launcher resolves the configured data directory and attempts a nonblocking exclusive lock on `updater.lock`. While holding that lock, it checks the active `current` target for a regular `.update-in-progress` marker. A valid saved release target is restored with a temporary symlink plus atomic rename; the `legacy` marker removes `current` so the existing flat-install fallback is selected. The launcher then releases the lock and starts the selected application. If the lock is busy, recovery does not touch `current`; the updater owns the active health-check/rollback sequence. Malformed or unsafe recovery state produces an actionable startup error and preserves files for manual recovery.

## Verification

- Unit tests cover integer and string port acceptance, malformed and out-of-range rejection, and parity between endpoint resolution paths.
- Launcher tests cover stale-marker rollback to a previous release and legacy install, no-op with no marker, and no rollback while `updater.lock` is held.
- Updater preflight tests ensure an old installed launcher blocks queueing with the existing setup instruction, while the capability-marked launcher allows it.
- Run focused regressions, the core suite, lint/type checks, `bash -n update.sh`, and `git diff --check`.

## Decision

Approved: proceed with the selected launcher-based recovery and port normalization described above.
