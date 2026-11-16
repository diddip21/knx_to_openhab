# GitHub Issue -> OpenCode plan -> maintainer approval (stage 2)

This stage **does not implement code, create feature PRs, or automatically merge**.
The OpenCode planner runs in GitHub-hosted Actions with no model API key, and
uses the same Superpowers plugin tested in draft PR #94.

## Installation

1. Merge the prerequisite free-model smoke test PR #94 (or ensure its
   `opencode.jsonc` already exists on `main`).
2. Merge this planner PR after its `AI issue planner controller tests` pass.
   **Issue and comment webhooks execute workflows from the default branch only.**
3. In **Actions -> Set up AI issue labels -> Run workflow**, select `main`
   and launch the label bootstrap once. It creates/updates:
   - `ai:plan` — start/restart planning
   - `ai:waiting` — waiting for answer or approval
   - `ai:approved` — plan approved, not implemented
4. Add the **`ai:plan`** label to an open issue while logged in as the
   repository owner. The agent creates either precise questions or a
   versioned implementation plan in an issue comment.
5. Reply `/ai answer Both legacy and YAML formats` to supply details and
   request a revised plan. Use `/ai approve v1` (or the current version)
   to approve the finished plan.

## Example

- You add `ai:plan` to issue #123.
- Bot writes: `OpenCode · Implementierungsplan v1` and adds `ai:waiting`.
- You write: `/ai answer Bitte auch Legacy-Things unterstützen`.
- Bot generates v2. The approval of v1 is now invalid.
- You write: `/ai approve v2`.
- The controller checks owner identity, actual plan version, status and issue
  title/body digest. It then adds `ai:approved` and removes `ai:waiting`.
  Nothing is implemented yet.

## Safety and behavior

- Only the repository owner (`github.actor == github.repository_owner`)
  can trigger planning and approval. Other issue edits can only run the
  deterministic stale-approval invalidation; they cannot call the model.
- Issue comments and title/body are untrusted data. All interpretation of
  `/ai` commands and plan versions is deterministic Python, not LLM reasoning.
- No external issue event is checked out; only default-branch source is used.
- Planning model and Superpowers skills have **read-only tool permissions**.
- The model receives no GitHub write token or external provider API key.
- GitHub's own action step performs comments and label updates.
- The command filter accepts the same trimmed, case-insensitive `/ai` grammar
  as the Python controller; unrelated owner comments are deterministic no-ops.
- The workflow never runs on pull-request comments.
- A plan's SHA-256 issue digest must still match before publication and approval.
- A new plan invalidates the previously approved label.
- Editing an approved issue's title or body removes the stale approval and
  returns it to `ai:waiting` when planning is still enabled.
- The action group serializes runs for one issue to reduce race conditions.
- Free models are external services with changing availability and data terms;
  don't put private ETS project data or secrets in public issues.
- The returned model output is bounded and schema-validated.
- No automatic paid-model fallback.
- CI remains unchanged.

## Testing before enabling live issue triggers

The `AI issue planner controller tests` workflow runs on the PR and checks
trigger selection, versioning, stale approvals, owner restrictions, bot-state
provenance, invalid commands, and JSON parsing. This does not by itself
validate successful end-to-end AI planning. After merge/bootstrap, assign
`ai:plan` to a **non-critical test issue** to verify the complete path.

## Known limits

- Only the owner can approve; delegated maintainer teams are not supported
  yet. This avoids trusting a model to authorize itself.
- If an issue is changed during a planning run, its output can be stale; the
  approval digest catches it, requiring a fresh plan.
- Issue titles and descriptions are each limited to 12,000 characters. Larger
  issues are rejected before calling the model so no acceptance criteria are
  silently omitted from the plan.
- The revised plan comment is published before changing approval labels, so a
  failed comment write cannot reopen approval of the old plan. A later label
  write can still fail after the new plan is published; rerun planning to
  restore the waiting labels.
- The next stage will implement authorized plans on a separate branch with
  a draft PR and the existing CI. That stage is NOT enabled by these files.
