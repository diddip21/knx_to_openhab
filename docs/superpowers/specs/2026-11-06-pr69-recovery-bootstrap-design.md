# Active Release Recovery Bootstrap Design

## Intent

Close the remaining deployment and recovery gaps found in review of the
active-release venv repair:

- Keep the repair entry point available independently of a particular release.
- Ensure the root-installed systemd launcher gets the fallback behavior through
  the supported installer path.
- Preserve custom `KNXOH_PATHS_FILE` configurations across sudo environment
  sanitization.
- Prevent a `current` pointer change between target validation and updater-lock
  acquisition from causing a stale release to be repaired.

## Goals

- Install a stable repair helper under
  `/usr/local/libexec/knx_to_openhab/repair_release_venv.sh` from `setup.sh`.
- Install the current `launch_update.sh` from `setup.sh` and verify the installed
  copy's behavior, including fallback when the active interpreter is executable
  but unusable.
- Let `setup.sh` bootstrap an older active release that has no release-local
  repair helper: install the stable helper and launcher, then repair the current
  release before restarting the Web UI.
- When the stable helper is absent, make the updater's recovery message direct
  an administrator to run the active release's setup script from an interactive
  SSH session. That setup command must explicitly carry
  `KNXOH_INSTALL_DIR`, `KNXOH_CONFIG_DIR`, `KNXOH_DATA_DIR`, `KNXOH_BACKUP_DIR`,
  and `KNXOH_PATHS_FILE`; `setup.sh` must honor the supplied paths-file value.
  When the helper is present, print a direct helper command.
- Pass `KNXOH_INSTALL_DIR`, `KNXOH_DATA_DIR`, and `KNXOH_PATHS_FILE` explicitly
  in the recovery command so it works even when `sudo -u` drops the caller's
  environment. Also pass the resolved release that emitted the recovery
  command; after acquiring the shared `updater.lock`, reject the operation if
  `current` has moved to another release.
- Acquire the shared `updater.lock` before resolving and validating `current`,
  then reject stale or out-of-release paths without touching a venv.
- Preserve legacy-install setup behavior and avoid adding sudoers capabilities
  or Python dependencies.

## Non-goals and Deployment Boundary

- A pre-change updater script cannot print a recovery command it does not
  contain. An installation whose active release predates this recovery code and
  already has a broken venv requires an administrator to run `setup.sh` from an
  updated source tree as a one-time bootstrap; no code inside that broken,
  pre-change release can self-install the fix.
- Normal release updates do not write root-owned files in `/usr/local`. The
  stable launcher and helper are refreshed through the existing administrative
  `setup.sh` path, not by broadening the updater's sudoers policy.
- Do not change release selection, activation, rollback, or dependency sets.

## Approaches

1. **Stable helper and launcher through setup — selected.** Install both
   root-owned systemd helpers from `setup.sh`; if a transactional `current`
   release exists, run the stable repair helper as `knxohui` before restarting
   services. This makes the helper independent of release contents and uses the
   existing administrative migration path for protected files. Existing
   pre-change installations with a broken venv need one explicit setup run from
   updated source.
2. **Keep release-local recovery and document manual repair.** Avoid installer
   changes, but a release missing the helper remains unrecoverable by the
   suggested command and the separately installed launcher can remain stale.
3. **Add a new root service action for helper/launcher deployment.** This could
   make updates refresh protected files automatically, but requires changing
   the root action helper and sudoers policy and still needs a bootstrap for
   installations whose installed action helper predates the new action.

The stable setup-owned helper is selected because it closes the release-local
dependency without granting the web updater additional root write authority.

## Design Constraints

- The stable helper takes its install directory, data directory, and paths-file
  location from explicit environment values passed by the caller; it validates
  these against `knxoh_paths.get_paths()` loaded from the stable install tree.
- The helper acquires the data-directory `updater.lock` before resolving and
  validating `current`; the expected release passed by the updater must still be
  current, and both paths must resolve beneath `$INSTALL_DIR/releases`.
- The helper repairs the selected release's venv at its final path, as
  `knxohui`, using that release's `requirements.txt`, `pip check`, and required
  module import validation. Failure restores the previous venv.
- `setup.sh` runs the stable helper only when `current` is a transactional
  symlink. Legacy setups continue without an active-release repair attempt.
- If the stable helper is missing, `update.sh` emits a shell-escaped
  `sudo bash <active-release>/installer/setup.sh` command; setup installs the
  helper/launcher and performs the active-release repair before service restart.
- Direct repair guidance uses shell-escaped assignments for all three paths and
  shell-escapes the stable helper path.
- Setup fallback guidance shell-escapes and passes all configured installation,
  configuration, runtime-data, backup, and paths-file values through
  `sudo env`, so the setup fallback does not depend on environment preservation.
- The launcher installed at `/usr/local/libexec/knx_to_openhab/launch_update.sh`
  is the exact launcher covered by the fallback regression.

## Acceptance Criteria

- `setup.sh` installs both root-owned launch scripts and invokes the stable
  repair helper for an existing transactional release before restarting the
  Web UI; legacy install setup skips repair.
- An active release without its own helper is repairable using the stable
  helper installed by setup.
- Recovery works when `sudo` removes caller-provided path environment variables
  and the paths file/install/data paths contain spaces.
- A pointer switch during lock acquisition is rejected before any venv changes.
- A previously installed launcher refreshed through setup falls back to the
  stable worker when active Python exits unsuccessfully; missing/non-executable
  behavior remains compatible.
- Existing successful recovery, rollback-on-failure, and updater-lock behavior
  remain covered and pass.
