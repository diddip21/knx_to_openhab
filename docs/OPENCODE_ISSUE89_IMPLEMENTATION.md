# Pilot: approved HomeKit Issue #89 → OpenCode → Draft PR

This isolated implementation pilot extends the proven README-only issue #96
workflow **without changing its permissions or behavior**. It supports **only**
maintainer-approved [Issue #89](https://github.com/diddip21/knx_to_openhab/issues/89),
plan v2.

## Why a new workflow?

The existing `opencode-issue-implement.yml` is deliberately restricted to
issue #96 and README.md. The issue #89 plan requires coordinated generator,
API, configuration, CLI, Web UI, translations, tests and documentation changes.

We avoid expanding write access for all issues. Instead this workflow has a
hard-coded, separately reviewable file whitelist.

## How to run the pilot

1. First reconcile `dev` with `main` (see
   [dev quickstart](AI_DEV_TO_MERGE_QUICKSTART.md)); `dev` must contain the
   current `main` commit without losing its unique work.
2. Review and merge the PR that introduces
   `.github/workflows/opencode-issue89-implement.yml`.
3. In Issue #89, the repository owner posts the exact comment
   `/ai implement v2` **after** the merge. The existing `/ai approve v2`
   and `ai:approved` label are necessary but do not automatically start
   implementation.
4. Observe the GitHub Actions workflow `OpenCode approved HomeKit issue 89
   implementation`.
5. The read-only-token `implement` job verifies the owner, approval receipt,
   latest plan version, unchanged issue title/body and valid command.
6. A dynamically selected **allowlisted free OpenCode model** uses the
   restricted `issue89-implementer` agent and Superpowers. It may edit only
   whitelisted HomeKit, settings, UI and test files. No GitHub write token.
7. A separate publisher independently rechecks issue approval and file
   allowlist, then creates **one Draft PR against `dev`** on a new branch and explicitly
   dispatches the project's CI workflow. It **never auto-merges**.

The Actions definitions and validators remain on `main` (GitHub Default Branch),
while the agent reads source from `dev`. The workflow fails closed if `dev`
does not include the current `main` revision or uses an altered OpenCode
configuration/agent policy. It does not change `main` or merge into `dev`.

The runner allows a bounded set of text files and rejects changes to
scripts, actions, dependencies and arbitrary paths. At least one regression
test and key generator/UI files are required. Partial or invalid output fails
closed; inspect the GitHub Actions logs.

## Review checklist

- Is `sendUpDownForExtents=true` present at the **correct effective**
  `WindowCovering` group metadata location for old and new configs?
- Does explicit `false` survive loading, saving and CLI generation?
- Are `stop` and `stopSameDirection` independent and disabled by default?
- Does the tri-state HomeKit mode preserve ETS auto-detection when unset?
- Is the displayed effective mode correct in preview, job state and API?
- Do legacy metadata and openHAB 5.2 YAML parse to equivalent semantics?
- Are generated IDs, groups and HomeKit `Instance` metadata preserved?
- Do DE and EN translations and UI setting roundtrips work?
- Do new unit, integration and Playwright tests pass?
- Do documentation, screenshots, and changelog explain the default change?
- Does a real KNX blind maintain its end position? **Hardware validation
  cannot be performed by GitHub Actions** and remains open until confirmed.

If the agent cannot create reliable UI screenshots under its read/edit
permissions, those are explicitly follow-up work. Do not mark issue #89
complete or merge the generated PR without checking them.

## Threat model / limitations

- Only the repository owner may initiate a run; exact approved plan v2
  and original issue digest must still match.
- Source code and issue bodies are untrusted data; only trusted scripts
  validate and publish. The privileged job **never executes** AI-generated code.
- After publication, the existing CI runs untrusted candidate tests
  without a GitHub write token.
- File sizes, file count, diff line count and overall artifact size are capped.
- New model IDs are not automatically trusted. The router uses only the
  reviewed free-model allowlist, with no paid fallback.
- The workflow may fail to finish a complex issue in one pass, hit free-tier
  limits or produce failing tests. That is a failed or reviewable pilot,
  **not** a reason to bypass owner approval or auto-merge.
- Changes to the approved plan, the title/body or the default branch between
  authorization and publishing fail the run. Rerun from a new owner command.
