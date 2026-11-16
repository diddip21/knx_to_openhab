# Active Release Virtualenv Recovery Design

## Intent

Make a transactional installation recoverable when the active release's
`venv/bin/python` is missing or unusable. Today `update.sh` rejects a
transactional release at its early completeness check before it can print the
later setup guidance. Running `setup.sh` would rebuild the stable installation's
venv, not the active release's per-release venv checked by the updater.

## Goals

- Give administrators a copy-paste-safe recovery command for a missing active
  release virtual environment.
- Rebuild the environment at the active release's final `venv` path so generated
  entry-point shebangs remain valid.
- Run repair as the `knxohui` service account, not as root, and serialize it with
  the updater's existing lock.
- Reject a stale or non-current release target and preserve/restore any partial
  prior venv if reconstruction fails.
- Prove that the emitted recovery command repairs the active release and that a
  subsequent updater run passes the missing-venv check.

## Non-goals

- Change stable-install or credential migration behavior in `setup.sh`.
- Change the release selection, activation, rollback, or dependency set.
- Automatically repair environments during an update run.

## Approaches

1. **Dedicated active-release repair script — selected.** Add a focused
   `installer/repair_release_venv.sh`, invoked as `knxohui` from the missing-venv
   recovery message. It validates that its containing release is the current
   target under the installation's `releases/` directory, takes the shared
   updater lock, and rebuilds that release's venv at its final path. This limits
   repair scope and avoids running service-owned release code as root.
2. **Extend `setup.sh`.** Teach the general installer/migration script to also
   repair the current release. This avoids another script but couples a narrow
   repair to broad system, service, and configuration changes.
3. **Require manual rollback/reinstallation.** Avoid adding repair logic and
   instruct users to restore a healthy release or reinstall manually. This is
   smaller but leaves recovery less actionable and easier to perform incorrectly.

The dedicated script is selected because it repairs exactly the environment
the updater validates while leaving the existing setup/migration workflow
unchanged.

## Design Constraints

- Keep the updater's normal behavior unchanged when the active venv is healthy.
- Permit the existing stable launcher/worker fallback to start the shell updater
  when the active venv is unavailable; do not stop before the actionable
  recovery branch.
- Derive the active release from the resolved `current` link and reject paths
  outside `INSTALL_DIR/releases/` or a release that is no longer current.
- Use the same data-directory `updater.lock` as `update.sh` to prevent repair
  racing an update or pointer transition.
- Run environment creation and dependency installation as `knxohui`, using the
  active release's `requirements.txt`; do not create root-owned venv files.
- Create the environment at `$APP_DIR/venv` (not a temporary path subsequently
  moved), since venv scripts embed their creation path in shebangs.
- On dependency-install or validation failure, remove only the partial new
  environment and restore any prior unusable environment that was preserved.
- Shell-escape the complete helper path in the recovery command.

## Acceptance Criteria

- A transactional release with an existing directory but no executable
  `venv/bin/python` reaches an actionable recovery message instead of exiting at
  the early completeness check.
- The message invokes the helper as `knxohui` and targets the resolved active
  release path.
- The helper refuses a stale/non-current target, an unsafe release path, or a
  busy updater lock without changing the active pointer.
- Successful repair creates a runnable venv at the active release's final path,
  passes `pip check`, and lets a subsequent updater run pass the venv preflight.
- Failed repair leaves the release pointer unchanged and restores any previous
  venv directory; no unrelated release or stable-root files are modified.
- Legacy install recovery and existing setup/migration commands remain
  compatible.
