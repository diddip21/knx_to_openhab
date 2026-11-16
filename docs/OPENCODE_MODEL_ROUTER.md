# Dynamic free-model selection for OpenCode

This router selects **one working model per GitHub Actions run**. It does
not purport to identify the world's strongest model or dynamically discover
every no-cost model.

## Eligible models and privacy

Only the audited allowlist is eligible:

- `opencode/glm-5.3-flash-free`
- `opencode/deepseek-v4.1-flash-free`

Both were successfully exercised anonymously in our smoke tests and were
listed as free and following zero-retention / no-training policies in the
[OpenCode free-model documentation](https://opencode.ai/docs/console/models/)
on 2026-11-15. Model availability, pricing and privacy statements may change.
Before adding another model, review its costs, geographic availability and
privacy policy. **No paid or unreviewed free model is ever selected.**

## Selection

Each planning or approved README-only implementation run:

1. Starts OpenCode on a GitHub-hosted runner without an API key.
2. Calls `opencode models opencode --refresh` (with a compatible fallback to
   `opencode models` if the first command fails).
3. Keeps only complete model IDs in the audited allowlist.
4. Invokes a bounded read-only `ci-smoke` agent for each candidate, without
   `GITHUB_TOKEN` or provider keys. A successful probe must complete a
   Superpowers `skill` tool call, a repository `read` tool call, and produce
   the standalone `ROUTER_OK` marker.
5. Scores candidates using these observed capabilities, a small
   project-specific factual answer (legacy + YAML), and response time.
6. Selects the highest passing score with deterministic ties; writes the
   selected model to GitHub Actions step output. The downstream OpenCode
   step uses that exact model for the **actual task**, with the same
   restricted agent and approval controls as before.

If a model is rate-limited or its probe fails, another approved free model
may win. If **no** approved free model passes, the job fails closed. There
is **no paid fallback**, no arbitrary model discovery, and no unapproved
provider use.

This is a lightweight connectivity/tool-use and factual **smoke benchmark**.
The score is not an independent measure of full code quality or deep
reasoning ability. Probes consume additional free requests and the
availability and scoring are reassessed for each run.

## Running tests

- Unit tests: `pytest -q tests/test_opencode_model_router.py -o addopts=`.
- CI: `OpenCode free-model router tests` runs the unit suite and a live
  matrix of `plan` and `implement` on eligible same-repository PRs.
- The router writes `$RUNNER_TEMP/model-router.json` and a concise GitHub
  job summary describing candidates, timings, scores and selected model.

The existing OpenCode planning and README-only implementation workflows
remain separate from approval and publishing. This change does not
enable automatic merging, modify generated configuration or expand the
implementer's file-write scope.

## Limitations and next improvements

- An availability probe can succeed while the subsequent full issue
  task fails or hits a later rate limit. The current workflow **does not
  retry the real task with a different model** because re-running
  implementation steps can have side effects. A future retry mode should
  isolate each attempt and discard unsuccessful changes first.
- Catalog output is advisory, not definitive proof of price. The allowlist
  and privacy review are mandatory and require maintenance.
- The factual smoke check is intentionally small. Longer-term quality
  evaluation should include a stable suite of project-grounded planning
  and implementation tasks, independent correctness checks, and
  historical success metrics. Do not confuse a fast response with
  intrinsically better code.
- No credentials or confidential ETS project data should be added to
  issue descriptions or these test prompts.
