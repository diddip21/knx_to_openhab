# OpenCode + Superpowers free-model smoke test

This is **stage 1 only** of a proposed GitHub-Issue planning workflow. It does
not react to issues, edit code, comment, open PRs, or change the existing CI.

## What it tests

The workflow `.github/workflows/opencode-free-smoke.yml` runs on a same-repo
pull request that changes its files, and can be launched with
`workflow_dispatch` once it exists on the default branch.

Each matrix job uses a fresh GitHub-hosted Ubuntu runner, installs OpenCode V2,
and selects **one specific free model** without configuring an API key:

- `opencode/glm-5.3-flash-free`
- `opencode/deepseek-v4.1-flash-free`

Superpowers is installed as an OpenCode V2 plugin from the pinned upstream
`v7.0.2` tag. A restricted `ci-smoke` agent tries to use the `skill`
tool to load `brainstorming` and read the existing `AGENTS.md`.

The job is successful only if the model returns a standalone response line
containing exactly `SMOKE_OK`. The structured event stream must also record a
completed `skill` call requesting `brainstorming` and a completed `read` call
whose path resolves exactly to the checked-out `AGENTS.md`. OpenCode V2
declares the skill argument as `name` and the read argument as `filePath`; the
smoke validator also accepts legacy event aliases `id` and `path`. OpenCode loads the JSONC
configuration itself; the workflow does not parse it as strict JSON. The
response and event stream are available in the run's artifacts/summary for
inspection.

## Costs and limits

No OpenCode account, OpenAI API key, paid provider, or GitHub Copilot is
configured. The exact `-free` model IDs prevent accidental paid-model
fallback. These free model promotions and anonymous access may end or require
authentication later. If either model stops being available, **the job fails**;
it does not switch to a paid model. Public-repository standard GitHub-hosted
Actions runners currently have no per-minute charge, subject to GitHub policies.

## Security and scope

- `GITHUB_TOKEN` has only `contents: read`; checkout does not persist it.
- No repository secrets or provider credentials are passed to the agent.
- The agent is configured to deny tools by default, allowing only local
  read/search and skill loading.
- Fork PRs do not execute this diagnostic.
- Output is diagnostic, not approval to implement issue automation.
- Upstream installer/plugin packages and externally hosted models are
  dependencies. For a production bot, pin dependencies and review their
  permissions and data-handling terms before expanding privileges.

## Inspecting the first test

1. Open the draft PR that adds these files.
2. Open **Checks**, then **OpenCode + Superpowers free-model smoke test**.
3. Look at the separate GLM and DeepSeek matrix results.
4. Open each job summary and diagnostic artifact if it fails.

`workflow_dispatch` cannot normally start a new workflow until its file is
on the default branch. The same-repository `pull_request` trigger exists so
the initial smoke test can execute before merge.

This is intentionally independent of `.github/workflows/ci.yml`.
