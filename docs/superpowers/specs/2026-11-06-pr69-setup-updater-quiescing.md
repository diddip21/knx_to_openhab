# PR #69 Setup/Updater Quiescing Follow-Up

## Intent

Prevent `installer/setup.sh` from changing application or runtime files while
the independent `knxohui-update.service` is active or has a queued start.

## Chosen Design

After stopping the Web UI (which prevents new UI-triggered update requests), run
a setup quiescing helper before any application/runtime mutation. The helper
waits for an already-running transactional updater to finish, cancels queued
non-stop jobs for the updater unit, and verifies that the unit is inactive with
no remaining jobs. It fails closed on systemd inspection/cancellation errors or
timeout. If the unit is not installed, setup proceeds for legacy/first installs.

This avoids interrupting an active transactional update while preventing queued
work from racing setup. The later repair helper continues to use its existing
shared updater lock and expected-release check.

## Requirements

- Stop the Web UI before quiescing updater work.
- Complete updater quiescing before the first application, configuration,
  runtime-data, backup, or venv mutation.
- Wait for active updater work to finish; cancel queued starts without treating
  a missing unit as an error.
- If updater state cannot be proven inactive and job-free before timeout, abort
  before mutations and let existing setup failure recovery restore services.
- Do not add sudoers permissions or alter the updater lock contract.
- Preserve first-install and legacy setup behavior when the updater unit is not
  loaded.

## Acceptance

- Tests simulate both an active updater that becomes inactive and an inactive
  unit with a queued start; setup's quiescing logic waits/cancels before returning.
- A setup wiring regression proves the helper runs after Web UI stop and before
  the first mutating setup command.
- Failure to inspect/cancel the updater or a timeout fails before mutations.
