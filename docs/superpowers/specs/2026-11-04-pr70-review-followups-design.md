# PR #70 review follow-ups design

## Intent

Close the three newly reported review findings on PR #70 while preserving the
existing isolated systemd updater and transactional release activation. The
goal is that published releases remain runnable after relocation, interrupted
request publication can recover, and the UI reports success only after health
validation.

## Scope

- Create the release virtual environment only after the app tree is at its final
  release path, and clean up an unpublished candidate on failure.
- Never overwrite or discard an existing pending update request. If the worker
  is inactive, allow it to process the already-published request; if it is
  active, report that the request is already in progress.
- Trigger the UI success dialog only on the final successful-update log marker,
  not when the service restart begins.
- Add regression coverage for the moved venv launcher, stale pending requests,
  and premature UI success signaling.

## Non-goals

- Redesign the updater service, request format, or release layout.
- Change release selection or queue a second request over an existing one.
- Change health-check or rollback policy beyond ensuring the UI waits for its
  result.

## Approaches

1. **Targeted fixes in the current flow (selected).** Keep the existing staging,
   systemd worker, and health-check design; correct the three identified edge
   cases with focused regression tests. This minimizes migration and review
   risk while retaining the current architecture.
2. **Redesign the updater and request queue.** Replace the existing transaction
   and queue semantics with a broader worker protocol. This could address more
   lifecycle states together, but is unnecessary for these findings and would
   expand the PR substantially.

## Implementation calls

- Move the extracted application into its final release directory before
  creating its virtual environment; retain cleanup ownership until activation
  succeeds.
- Treat an existing request file as the durable request to resume, never as a
  slot to replace. Once published, keep the request across worker-start errors
  so a later trigger can resume it; do not let a concurrent start failure
  delete the request before the worker claims it.
- Leave the restart log message intact for progress reporting, but make the UI
  success dialog depend only on `Update completed successfully`.
