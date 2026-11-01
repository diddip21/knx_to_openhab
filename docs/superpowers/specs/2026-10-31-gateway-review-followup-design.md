# Gateway review follow-up design

## Intent

Address the four new Codex findings on PR #55 and the local finding in the deploy
rejection path before asking for another review. Keep gateway state, persisted
configuration, and the managed OpenHAB files consistent after live actions and
generic rollback.

## Goals

- Prevent gateway state/reset from using deployment metadata that no longer
  describes the restored files.
- Keep the UI's saved IPv6 override in the same canonical form the backend
  persisted.
- Ignore DSL bridge examples inside comments without adding a parser dependency.
- Return the actual restored file IP from Undo, separately from the saved
  override.
- Ensure a rejected deploy preflight does not run the deployment rollback writer.
- Add focused regression tests for each accepted finding.
- Commit a screenshot of the finished gateway settings UI without secrets or personal data.

## Non-goals and constraints

- Do not query OpenHAB runtime or network state.
- Do not add dependencies or change the API's existing route shapes.
- Preserve safe managed-file writes and acquire locks in the existing
  `operation_lock` then `gateway_state_lock` order for operations that change
  deployment state.
- Do not infer deployment/ETS identity from arbitrary backup file contents.

## Approaches

1. **Fail closed after generic rollback (selected):** Invalidate deployed-job
   metadata and the live Undo snapshot so gateway live actions remain disabled
   until a successful deploy establishes a known target. This works for
   arbitrary and legacy backups, but temporarily removes live actions after
   rollback.
2. **Reconstruct the previous live target:** Persist deployment and ETS-source
   metadata with every backup and restore it with the files. This preserves live
   actions but requires metadata migration and fallback rules for old backups.

The user selected the fail-closed behavior because a generic rollback can select
a backup whose deployment identity is not reliably known.

## Follow-up findings on `0548a86`

The user selected **invalidate deployment metadata when the active job is
deleted**. Deleting the active history record will remain allowed, but the
operation must persist all deployed flags as false before removing that record
from memory, then clear the gateway Undo snapshot. This prevents lookups from
falling back to an older job whose files are not live. If persistence fails,
retain the job and its prior metadata.

When a deploy writes files but cannot persist its new deployment metadata,
restore the previous `deployed`, `deployed_at`, and `deployment_id` values in
memory while restoring files from the pre-deploy backup. This preserves a
previously committed deployment identity during a failed same-job redeploy.

After successful deploy or generic rollback, the browser must reload gateway
state so the Devices pane and its available controls match the backend's
current deployment target. Failed actions do not report a successful
transition.

Capture a safe sample screenshot of the Devices pane after rollback invalidates
the deployment target, showing the refreshed unavailable state and disabled
live controls.

## Proposed behavior

- Serialize generic rollback with both deployment and gateway-state operations.
  After validating the backup, persist invalidated deployment flags before
  restoring files; if metadata persistence fails, do not write files. If file
  restoration fails, remain fail-closed rather than expose a possibly stale
  target. Clear the old live Undo snapshot after successful restoration.
- On successful live apply, use the backend's returned `saved_override` for
  both the gateway input and `currentConfig`.
- Strip DSL line and block comments with a small quote-aware scanner before
  matching unmanaged bridge declarations; fail closed on an unterminated block
  comment.
- Parse the snapshot's previous file content with the shared gateway parser and
  use that file IP in Undo's response; keep `saved_override` as the persisted
  configuration value.
- Keep the unmanaged-bridge recheck under deploy locks, but outside the
  rollback `try` so preflight rejection cannot restore a backup.

## Verification and merge gate

Add regression tests for rollback metadata invalidation, IPv6 canonicalization,
commented DSL declarations, Undo's reported file IP, and no rollback write on
preflight rejection. Capture the canonicalized gateway settings view at
`docs/screenshots/gateway-ip-canonicalized.png` and reference it from the PR.
Run focused tests and project checks, push without force, reply to the new
review threads, then merge only if the new GitHub review has no unresolved
findings and required CI checks pass.

## Follow-up findings on `023ad49`

### Intent and goals

Close the four new Codex findings without changing API shapes or adding
dependencies. Keep the displayed gateway target and enabled controls aligned
with persisted backend state after job deletion and config saves, and prevent
wall-clock changes from selecting a retired deployment.

### Active deployment approach

Two approaches were considered:

1. **Keep one `deployed` flag active (selected):** On a successful deploy,
   persist `deployed=false` for other jobs and `deployed=true` for the new
   active job. This matches rollback/deletion, which already invalidate these
   flags, and avoids adding a second identity system. Older staged jobs become
   deployable again after they cease to be active.
2. **Persist a separate active deployment ID or monotonic sequence:** Preserve
   the current historical `deployed` markers and UI eligibility behavior, but
   introduce additional persisted identity/ordering state and compatibility
   handling.

The user selected approach 1. `deployed_at` remains informational/legacy
metadata; newly successful deployments must not depend on its wall-clock order
to identify the active job. Existing persisted records may have multiple
`deployed=true` flags; their current fallback selection remains compatible
until the next successful deploy normalizes the flags.

For deployment persistence failure, restore every job's prior `deployed` flag
and the redeployed job's prior `deployed_at` and `deployment_id`, then retain
the existing managed-file backup restoration behavior.

### Other selected behavior

- After a successful active-job deletion, await a gateway-state refresh so an
  invalidated target clears the Devices pane and disables live actions.
- After a successful config save, await a gateway-state refresh so stale Undo
  availability is removed when the saved gateway override makes its snapshot
  stale. A failed save must not be presented as a successful refresh.
- Reuse the existing quote-aware, length-preserving DSL comment scanner when
  locating managed-file bridge declarations, brackets, active properties, and
  comma-separated property segments. Apply edits at the matching offsets in the
  original content so commented examples and unrelated comments remain intact.
  Ignore commented declarations without treating a commented-only bridge as
  live configuration.

### Scope and verification

Add focused regression tests for each finding: a backward-clock redeploy and
failed metadata persistence, delete/save UI state refresh, and commented DSL
bridge handling for live gateway edits. Keep current lock ordering and
deployment file safety; do not change generated formats, query OpenHAB runtime,
or add dependencies. Re-run focused backend/UI tests, lint and full required CI;
request another Codex review and merge only with no unresolved findings and
green required checks.
