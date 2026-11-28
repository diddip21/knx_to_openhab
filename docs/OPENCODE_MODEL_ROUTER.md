# Dynamic free-model selection for OpenCode

This router selects the **highest-scoring eligible free model for the current
task and run**, with a ranked list of verified fallbacks. Planning, implementation
and repair have different correctness checks. Scores describe these observed
checks, not a claim to identify the world's strongest model.

## Eligible models and privacy

### Independent optional OpenRouter route

The owner authorized additional API providers on 2026-11-28, strictly free.
OpenRouter is optional: without `OPENROUTER_API_KEY`, anonymous OpenCode routes
continue working and no OpenRouter catalog/probe request is made.

Reviewed candidates are currently `nvidia/nemotron-3-ultra-550b-a55b:free`,
`nvidia/nemotron-3.5-lightning:free` and `google/gemma-4-31b-it:free` under
`openrouter/`. Each run checks the public catalog for zero prompt/completion
and other advertised charges, tool support and at least 65,536 context tokens.
Unknown, paid, malformed or unreviewed entries are excluded. All candidates
still need the task-specific live probe; model size is not a ranking score.

Every OpenRouter process receives a controller-built V2 configuration with
`provider.max_price` set to zero for prompt, completion, request, image and audio,
`data_collection: deny`, `zdr: true`, required parameter support, no paid plugins,
and a model-fallback list containing only the exact selected free model.
The pinned CLI HTTP contract is verified against a local mock endpoint, without
real credentials or a paid request. See [OpenRouter price ceilings](https://openrouter.ai/docs/guides/routing/provider-selection#max-price)
and the [pinned OpenCode request-body schema](https://github.com/anomalyco/opencode/blob/v2.3.0/packages/schema/src/config/provider.ts).

Setup for the owner:

1. Create an [OpenRouter API key](https://openrouter.ai/settings/keys) with a zero
   spending limit. Do not enable automatic top-ups or paid fallback routes.
2. In [OpenRouter privacy settings](https://openrouter.ai/settings/privacy), enforce
   **ZDR only** for every model group and disable prompt/completion logging.
   Request-level `zdr: true` follows the account's Safety Retention choice; it does
   not independently exclude that tier. See [the current ZDR policy](https://openrouter.ai/docs/guides/features/zdr).
3. Add the key as repository Actions secret `OPENROUTER_API_KEY` in
   [repository secrets](https://github.com/diddip21/knx_to_openhab/settings/secrets/actions).
   Do not paste the key into issues, comments, commits or chat.
4. Manually run **OpenCode free-model router tests** on the reviewed branch.
   Its `workflow_dispatch` run may use this secret. PR-triggered probes and the
   unpublished PR replay remain secret-free. Production owner-authorized planning,
   implementation and repair expose this one key only to selection/generation steps;
   the isolated subprocess receives it only when its selected model is OpenRouter.

No OpenRouter account or secret has been created by this change. Its real capacity
and privacy-compatible free endpoints must be checked after setup; no passing
live OpenRouter inference is claimed without that evidence. Empty free/ZDR
capacity is an availability failure, never permission to spend or weaken privacy.

Provider account/authentication failures exclude all remaining models on that
provider. A separately authorized independent provider can be tried; the original
provider is not re-entered during the same planning run. Request-size and policy
violations still stop without truncating the research request.

### Anonymous OpenCode routes

Only the audited allowlist is eligible:

- `opencode/hy4-flash-free`
- `opencode/deepseek-v4.1-flash-free`

Both are listed as free and following zero-retention / no-training policies in the
[OpenCode free-model documentation](https://opencode.ai/docs/console/models/)
on 2026-11-28. Hy4 replaces the retired GLM free entry; its live validation is
required before deployment. Model availability, pricing and privacy statements may change.
Before adding another model, review its costs, geographic availability and
privacy policy. **No paid or unreviewed free model is ever selected.**

GLM-5.3-Flash Free is no longer in the current free-model catalog. An allowlist
entry is reviewed eligibility, not a guarantee that a
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
   It must also solve the stage-specific synthetic task:
   - `plan`: preserve defaults, explicit false, integer validation and the full
     configuration/API/generation/legacy/YAML flow.
   - `implement`: produce a normalization expression, independently tested on
     missing, positive, zero, negative, boolean, string and list inputs.
   - `repair`: correct an index boundary error, independently tested on negative,
     valid and out-of-range indices, including the exact upper boundary.
   Expression evaluation accepts only a bounded AST of comparisons, conditionals,
   boolean operations and direct `type`/`len` calls on the controller's fixtures.
   Imports, attribute access, arbitrary calls, arithmetic, loops and file/network
   operations are rejected before evaluation. Model code never runs in the repo.
5. Requires all task cases to pass. Scores passing candidates using a small
   project factual check (legacy + YAML) and latency; the factual check outweighs
   the entire speed bonus. A fast wrong answer is ineligible.
6. Selects the highest passing score with deterministic ties; writes the
   selected model to GitHub Actions step output and all passing candidates in
   score order to the report. The downstream OpenCode
   step uses that exact model for the **actual task**, with the same
   restricted agent and approval controls as before.

If a model is rate-limited or its probe fails, another approved free model
may win. If **no** approved free model passes, the job fails closed. There
is **no paid fallback**, no arbitrary model discovery, and no unapproved
provider use.

This is a lightweight tool-use and stage-specific **smoke benchmark**.
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

- Unit tests: `pytest -q tests/test_opencode_model_router.py tests/test_model_task_probe.py -o addopts=`.
- CI: `OpenCode free-model router tests` runs the unit suite and a live
  matrix of `plan`, `implement` and `repair` on eligible same-repository PRs.
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
  may use only another model verified for that task by this same router run.
  Planning preserves and verifies its source-bound research session when switching
  models. A request-rate limit receives at least a 60-second cooldown (or the
  provider's longer `retryAfterMs` if it fits the remaining budget), then the next verified
  candidate if available, otherwise one same-model continuation. Authentication,
  shared/account/daily quota and request-size failures stop; model rotation cannot
  fix those conditions. Implementation
  and repair restore allowed partial changes before their one fallback;
  policy or scope violations stop the run. See [AI automation](AI_AUTOMATION.md).
- Pinned OpenCode V2's `provider.free-limit` and `provider.model-budget-limit`
  explicitly recommend switching models. These model allowances permit only an
  untried verified alternate, never another identity or a blind retry of the exhausted
  model. `provider.quota`, `provider.budget-limit` and `provider.go-limit` stop.
  See the [upstream error mapping](https://github.com/anomalyco/opencode/blob/v2.3.0/packages/core/src/session/to-session-error.ts)
  and [wire schema](https://github.com/anomalyco/opencode/blob/v2.3.0/packages/schema/src/session-error.ts).
- A retired model can remain in an upstream cache or bundled snapshot.
  Discovery alone never selects it: the independent live read/skill probe
  remains mandatory. Two unsuccessful discovery attempts or no passing
  approved probe stop the workflow with diagnostics.
- Catalog output is advisory, not definitive proof of price. The allowlist
  and privacy review are mandatory and require maintenance.
- The correctness checks are intentionally small. Longer-term quality
  evaluation should include a stable suite of project-grounded planning
  and implementation tasks, independent correctness checks, and
  historical success metrics. Do not confuse a fast response with
  intrinsically better code.
- No credentials or confidential ETS project data should be added to
  issue descriptions or these test prompts.
