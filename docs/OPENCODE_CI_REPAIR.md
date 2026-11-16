# Auto-repair failed CI for approved HomeKit issue #89

This workflow adds **at most two** controlled OpenCode + Superpowers
follow-up changes to the already-approved HomeKit Draft PR. It does **not**
auto-merge, edit `main`, add paid providers, expand the original plan, or
permit unrelated PRs.

## What triggers it?

A completed **failed** `CI` run that was explicitly dispatched on a
bot-created branch of the form
`ai/issue-89-plan-v2-run-<run ID>`. Other PRs, user branches,
GitHub PR events, successful CI, and unrelated jobs are ignored.

The PR must remain a **Draft** and the author must be
`github-actions[bot]`. The controller retrieves live Issue #89 and its
comments to revalidate the maintainer's latest plan v2, approval receipt,
original implementation command, issue digest, open status and labels.
The PR head must exactly match the commit checked by the failed CI run.

## Safe workflow

1. A low-privilege job checks out the trusted default-branch validator
   separately from the **exact failing PR commit**.
2. GitHub's failed-job logs are fetched as **untrusted diagnostic data**.
3. A fresh approved-free-model probe selects a working OpenCode model.
   The model can read relevant files, load Superpowers
   `systematic-debugging` and `verification-before-completion`, and edit
   **existing** allowlisted HomeKit, Web-UI and regression-test files.
   Shell commands, git writes, arbitrary new files and secrets are excluded.
4. Trusted Python checks the candidate Git diff (existing whitelisted files
   only, bounded file count/changed lines/content size, no deletions, renames
   or whitespace errors). The candidate is stored as a short-lived artifact.
5. The separate publisher, which **never executes candidate code**, checks
   the live PR/issue/approval again. It verifies every candidate blob's
   SHA-256 and creates exactly one fast-forward-only commit on the existing
   Draft-PR branch: `fix(ai-ci): issue89 attempt 1` or `attempt 2`.
6. The publisher explicitly dispatches the existing `CI` workflow on the
   modified branch. If CI is still red, the cycle can repeat once more.
   If a third failure occurs, no more repairs are published; a maintainer
   must review it.

The existing CI retains its normal lint → core → UI dependencies and
runs candidate tests under the existing read-only permissions. Repair attempts
should fix the failure's root cause, **not weaken or skip tests**.

## Test and activate

- Validate `tests/test_ci_repair.py` in CI and review the privileged workflow
  before merging the infrastructure PR.
- After merge, the workflow lives on `main`. Subsequent *failed*
  `workflow_dispatch` CI runs on a matching Draft PR can trigger the
  automatic repair.
- The current PR #108 already has manual test corrections. If its current CI
  is green, the repair workflow **must not run**. A forced failing run should
  not be introduced merely to test the feature.
- The original HomeKit functionality still requires correct legacy/YAML
  metadata, Web-UI behavior, Playwright tests, screenshots and a real
  hardware test before any merge.

## Limits

- The allowlist is pinned to Issue #89, with an owner-approved v2 plan.
  Another issue requires new review and a separate, scoped design.
- Free-tier availability and capability may change; the router has **no paid
  fallback** and aborts if no approved model passes its read-only probe.
- A model can edit source but cannot directly publish any change. Unexpected
  files, stale PR heads, revoked approvals or invalid artifacts fail closed.
- Limits are a guardrail, not proof that AI-generated code is correct. All
  generated changes are reviewable and CI/hardware testing remains required.
- The privileged GitHub publisher cannot fully eliminate races with concurrent
  administrator branch updates; it serializes its own runs and requires
  fast-forward updates. Do not run this on third-party PRs.
