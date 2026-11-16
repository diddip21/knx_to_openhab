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

## Review-driven hardening

The fresh whole-branch review exposed lifecycle races at the boundaries between
the Web UI, the systemd worker, and release activation. These changes extend the
same targeted-fix approach; PR #70 must remain open until they are covered and
verified.

### Scope

- Serialize Web UI request publication and worker execution with one exclusive
  lock file in the runtime data directory. A request already pending or claimed
  must block a second request from replacing it or resetting its log.
- Initialize and fsync a new request's log before atomically publishing the
  request. On retry, surface the tag of the durable request and retain the
  actionable start status in the UI.
- Let an inactive worker recover an interrupted claimed request without silently
  deleting it; an active worker must be reported as in progress.
- Mark final-path release candidates while building them. On retry, remove
  unactivated marked candidates and abandoned staging trees, but never remove
  the path selected by `current`. The exit trap must make the same active-target
  check, independent of the timing of its activation flag.
- Add regression tests for activation interruption, candidate recovery, request
  lock/claim races, and stale success logs. Prevent ordinary UI tests from
  rewriting the committed screenshot.

### Selected approach

Use the existing filesystem and systemd design with a shared `flock` file and
explicit in-progress candidate markers. This closes the races at their shared
serialization boundary without introducing a new request database or queue
protocol. A broader multi-state queue redesign was considered but would expand
the change and migration surface unnecessarily.

### Additional implementation calls

- Both `Updater.trigger_update()` and `run_update_request.py` use the same
  `update-request.lock` in the configured data directory. The Web UI lock is
  non-blocking; the worker waits for it after systemd starts and holds it while
  claiming and processing the request.
- `update-request.running.json` is not a slot for another request. If the lock
  is available but a claimed request remains, restore it to the pending path
  before restarting the worker; if both paths exist, preserve both and report
  the conflict rather than deleting either.
- Write, flush, and `fsync` the per-request log header before publishing its
  request file. This ensures a retry cannot see an old success marker for a
  newly published request.
- A `.update-in-progress` marker is placed in the extracted app before moving
  it to its final release path. Cleanup removes marked candidates only when
  they are not the resolved target of `current`; successful health validation
  removes the new release's marker.
- Screenshot capture in the Playwright test is opt-in; the committed screenshot
  remains the reviewed artifact and routine test runs do not dirty it.
