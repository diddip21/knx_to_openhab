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

The same documentation lists GLM-5.3-Flash Free as deprecated on
2026-11-18. An allowlist entry is historical approval, not a guarantee that a
model is currently offered. Discovery and the live probe must still pass in
the current run; one available approved model is sufficient. A missing model
does not authorize substituting a different provider or another free model.

## Selection

Each planning, approved implementation or CI-repair run:

1. Starts OpenCode on a GitHub-hosted runner without an API key.
2. Calls `opencode models --standalone`, the supported command for the pinned
   OpenCode 2.3.0 CLI. It uses at most two discovery attempts, each limited to
   50 seconds. CLI failures, empty catalogs, and catalogs without approved models
   receive one retry. Invalid encoding or an oversized response stops discovery
   immediately. No persistent
   background server or unsupported legacy `opencode --refresh` arguments
   are used. See the [upstream command definition](https://github.com/anomalyco/opencode/blob/v2.3.0/packages/cli/src/commands/commands.ts)
   and [native catalog smoke test](https://github.com/anomalyco/opencode/blob/v2.3.0/packages/cli/script/catalog-smoke.ts).
3. Keeps only complete model IDs in the audited allowlist.
4. Invokes a bounded read-only `ci-smoke` agent for each candidate, without
   `GITHUB_TOKEN` or provider keys. A successful probe must complete a
   Superpowers `skill` tool call, a repository `read` tool call, and produce
   the standalone `ROUTER_OK` marker without a provider or tool failure.
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

## Failure diagnostics

An empty catalog, a catalog containing no approved candidates, and failed
probes are different outcomes. A successful CLI exit with an empty or
unparseable response is not treated as a completed probe. The report records
the discovery attempts and fixed failure codes separately from actual model
probes, so an unavailable candidate cannot be mistaken for a tool-use failure.

The router writes a versioned JSON report containing the task, status,
allowlisted candidate IDs, fixed failure codes, timings, byte/count metrics,
and probe flags/scores. Concise fixed diagnostic lines are also written to
the job log. Raw catalog text, unknown model IDs, prompts, model replies,
tool output, provider error messages and stderr are not included.

All three production workflows upload the report immediately after model
selection, including selection failure, as
`ai-model-selection-<run ID>-<attempt>`. Planning retains it for seven days;
implementation and repair retain it for three. The exact source file is
`model-router.json` for planning and `model.json` for implementation/repair.
No generation step needs to start for this diagnostic upload to run.
The original selection failure still blocks generation and publication.

## Running tests

- Unit tests: `pytest -q tests/test_opencode_model_router.py -o addopts=`.
- CI: `OpenCode free-model router tests` runs the unit suite and a live
  matrix of `plan` and `implement` on eligible same-repository PRs.
- The live test matrix retains its report as
  `model-router-<task>-<run ID>-<attempt>`, including failure, and checks the
  selected model against the same two approved IDs.

The existing OpenCode planning and scoped implementation workflows
remain separate from approval and publishing. This change does not
enable automatic merging, modify generated configuration or expand the
implementer's file-write scope.

## Limitations and next improvements

- An availability probe can succeed while the subsequent full issue task
  fails or hits a later rate limit. The bounded planner/generation runners
  may use only another model verified by this same router run. Implementation
  and repair restore allowed partial changes before their one fallback;
  policy or scope violations stop the run. See [AI automation](AI_AUTOMATION.md).
- A retired model can remain in an upstream cache or bundled snapshot.
  Discovery alone never selects it: the independent live read/skill probe
  remains mandatory. Two unsuccessful discovery attempts or no passing
  approved probe stop the workflow with diagnostics.
- Catalog output is advisory, not definitive proof of price. The allowlist
  and privacy review are mandatory and require maintenance.
- The factual smoke check is intentionally small. Longer-term quality
  evaluation should include a stable suite of project-grounded planning
  and implementation tasks, independent correctness checks, and
  historical success metrics. Do not confuse a fast response with
  intrinsically better code.
- No credentials or confidential ETS project data should be added to
  issue descriptions or these test prompts.
