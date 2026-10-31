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
