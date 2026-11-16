# Early CLI Update Guard — Design

## Intent

Prevent `install.sh --update` from making network or system changes when the
installation is already using transactional releases. The installer must tell
the operator to update through the Web UI before resolving a release or
installing packages.

## Goals and non-goals

- Detect `INSTALL_MODE=update` with an active `$INSTALL_DIR/current` symlink
  before release lookup, privilege/OS checks, or dependency installation.
- Preserve legacy Git-checkout CLI updates and all other installer modes.
- Do not implement transactional release activation in the CLI updater.

## Approaches

- **Guard immediately after `select_install_mode()` in `main()` (selected):**
  mode/path validation stays centralized, while the rejection runs before
  external or privileged work. This is the clearest boundary in the current
  flow.
- Guard inside `select_install_mode()`: also early, but mixes release-mode
  behavior into path/mode validation.
- Guard in `update_repository()`: rejected because release resolution and
  dependency installation have already happened by then.

## Verification

Add an end-to-end installer-mode test with a transactional `current` symlink
and sentinel `curl`/`sudo` commands. Assert the command exits with the Web UI
guidance before either sentinel runs. Keep existing legacy update tests green.
