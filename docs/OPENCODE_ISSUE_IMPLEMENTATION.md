# Approved Issue → OpenCode → Draft PR (stage 3 pilot)

This **opt-in pilot is restricted to issue #96 and README.md**. It does not
implement general issue coding or merge code into `main`.

## Prerequisites

- `opencode.jsonc` with Superpowers and the issue planning workflow are
  already on `main`.
- The latest OpenCode plan on issue #96 is approved (`ai:approved`).
- The issue title/body still match the digest in the approved plan.
- The repository owner explicitly writes `/ai implement v2` in issue #96.
  Plan approval by itself is **not** an implementation trigger.

## Workflow

1. `.github/workflows/opencode-issue-implement.yml` activates only for
   an owner's issue comment, with the exact issue number and command grammar.
2. The **unprivileged** `implement` job checks out trusted `main` with
   no persisted credentials, fetches the issue and comments, validates the
   latest plan version, owner approval, bot approval receipt and issue digest.
3. OpenCode (free GLM model) loads the Superpowers implementation skill and
   edits **only README.md**. The agent has no GitHub write token.
4. `scripts/issue_impl.py collect` checks a clean, README-only
   diff, a bounded change size and the corrected guide anchor. It uploads
   only the bounded candidate content and approval metadata.
5. The **separate privileged** `publish` job downloads the artifact,
   re-fetches the live issue/comments, rechecks approvals, issue digest,
   SHA-256 of the artifact and unchanged base commit/README.
6. Only after those gates, it creates one README blob/commit on an
   issue-specific `ai/issue-96-plan-v2-run-...` branch and a **draft PR**.
7. It explicitly dispatches the existing `CI` workflow for the branch.
   This is necessary because activity performed with `GITHUB_TOKEN`
   normally does not trigger conventional push/PR workflows.

The publisher never reads model-generated shell commands, and does not
apply patches to arbitrary files. Only the validated README blob is written.

## Limitations and safety

- The run fails closed if no matching approval exists, the issue changed,
  unexpected files changed, model tools were blocked, or the model is
  unavailable. It will not silently switch to a paid provider.
- The workflow permits only README changes in **issue #96**; making this
  general-purpose requires an additional review of scope and threat model.
- Model and Superpowers plugin code remain external dependencies. The
  free model has changing quotas and data terms. Public issues should not
  contain personal ETS data or secrets.
- The branch, once created, is intentionally **not merged automatically**.
  Every review finding must be resolved per `AGENTS.md`.
- The command must be posted **after** this workflow is merged to `main`.
  Historical approvals are not reprocessed.
- If CI dispatch fails after draft PR creation, the draft PR remains for
  inspection; retry CI manually from the Actions UI.
- GitHub may impose quotas or permission limits on public repositories.
  Keep permissions and usage under review.

## Verification

This PR adds `tests/test_issue_impl.py` and a dedicated, read-only PR test
workflow `Approved issue implementation guard tests`. The existing
`CI` workflow remains unchanged. Only merge this workflow after all tests
and code review are accepted.

Test commands after merge:

```text
/ai implement v2
```

Post that command in [Issue #96](https://github.com/diddip21/knx_to_openhab/issues/96),
not in a PR. Observe the "OpenCode approved issue implementation (README pilot)"
Action. When successful, inspect the created draft PR and its CI report.
