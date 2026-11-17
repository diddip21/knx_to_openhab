# Generic owner-approved AI workflow

This is repository tooling, not application runtime code. No controller contains
an issue number, HomeKit prompt, fixed plan version or per-feature write list.
Issue #89 is a test case, not a production exception. The old #89/#96 executables,
agents and duplicate guard workflows have been removed.

## Activation and migration

Review the infrastructure PR and its complete CI before manually merging it into
`main`. The issue-comment and workflow-run controllers live on this default
branch. Then synchronize the reviewed `main` into `dev`, preserving existing
work. No controller merges either branch. The shared CI definition and OpenCode
policies on `dev` must match trusted `main` before generation can start.

The hardware-gate removal from #116 is included in this generic implementation.
Do not reintroduce the old readiness script by resolving a merge conflict in
favor of the retired controller. Application PR #108 is not rewritten or merged.
Its old command has no explicit file scope and is NOT silently upgraded to the
new authorization protocol. Use a new approved plan for a fresh test run; retain
#108 as a comparison until the owner decides what to do with it.

## Normal issue-to-PR sequence

1. Describe the task and acceptance criteria; request planning using `ai:plan`.
   The existing read-only planner proposes changes, tests and exact paths.
2. Resolve questions using `/ai answer ...`. Review the current plan and post
   `/ai approve vN`. Wait for the bot's matching approval receipt.
3. Separately post the exact start command and the reviewed JSON file scope:

   ````text
   /ai implement vN
   ```json
   {
     "files": ["some_module.py", "tests/test_some_module.py", "docs/USER_GUIDE.md"],
     "create": ["tests/test_some_module.py"],
     "required": ["some_module.py", "tests/test_some_module.py"]
   }
   ```
   ````

   Replace `N` and the example paths. `files` is the complete allowed set;
   `create` authorizes missing files; `required` must actually be changed by the
   first implementation. Empty `create`/`required` lists are allowed. Only the
   repository owner's live, unedited command grants this scope. A model proposal,
   label, issue body or PR description does not grant write permissions.
4. The read-only generation job selects an approved free model, installs the
   pinned OpenCode CLI and builds literal agent permissions from the owner scope.
   Shell, external directories, Code Mode, network tools and subagents stay denied.
5. A separate publisher re-fetches the issue and all authorization comments,
   validates the candidate against trusted Git objects, and creates a Draft PR
   against `dev`. It explicitly dispatches the full existing CI.
6. A failed **dispatched CI** may trigger at most two repairs of the same
   bot-authored, open **Draft** PR, on the exact failed SHA. Repairs cannot add
   files or expand the original owner scope. Normal PR-CI failures, foreign
   repositories, Ready-for-review PRs, stale runs and revoked approval do not
   authorize repair. Manual commits never reset the two-attempt budget.
7. The read-only readiness workflow checks current plan/scope, current CI,
   human review, unresolved threads, mergeability and UI screenshot files when
   UI paths changed. It reruns after CI completion, PR/review events, and via
   Actions -> AI merge readiness (read-only) -> Run workflow -> PR number.
8. The owner reviews evidence, marks the Draft ready, and merges deliberately.
   Release remains a separate reviewed `dev` -> `main` change.

## Scope and safeguards

Literal ASCII repository-relative paths only; no wildcard, traversal, hidden
path, symlink, hardlink, deletion, rename or binary artifact. Normal application
source, documentation and test paths are supported. Automation, workflow,
installer, dependency, approval-policy and test-harness changes require a
separate human-led infrastructure PR. An owner command cannot override these
controller restrictions. Code changes must include a changed Python regression
test. Documentation-only changes do not need a fabricated test change.

Limits: 20 files, 300 KB per file, 1.25 MB total, 2,500 changed lines initially;
12 files and 650 changed lines per repair; at most two repair commits. The
publisher independently rechecks sizes, file bytes, hashes, original file modes,
new-file permissions, required files and changed-line counts. It never imports
or executes candidate code. Python runs isolated (`-I`) from trusted scripts.
Only the publisher has GitHub write permissions; only AI branches can be moved,
and repair pushes are fast-forward-only.

The original command, plan and normalized scope are hash-bound into the PR.
Editing or deleting those comments, changing the issue, replacing the plan,
removing approval, moving a branch, or rerunning CI while repair is in flight
causes a stop instead of a silent pass. A repeat of the same run with an existing
matching PR resumes CI without republishing code. Another PR for the same plan
is rejected. If branch creation succeeds but PR creation fails, inspect the
orphan branch manually; it is never silently overwritten. Concurrent manual
administrator mutations cannot be made transactional with separate GitHub API
calls; publication rechecks immediately before ref changes and fails closed
where a mismatch is observed.

No hardware test is required by software readiness. No real-device behavior is
claimed as validated by CI. Screenshot file presence is not proof of image
content: human visual review is still required. A successful model run is not a
test result. Tests and source still need independent review; a model can propose
incorrect behavior even within an authorized file list.

## Reproducible tests and evidence limits

`tests/ai_pipeline/` exercises different issue numbers and plan versions through
the same authorization, artifact, repair and publisher implementation. Negative
tests cover forged/edited approvals, scope changes, path escapes, symlinks,
oversized content, foreign PRs, stale commits and attempts, and repair caps.
Publisher/API tests call the production JavaScript against deterministic API
fixtures. Contract tests verify permissions, trusted checkouts, triggers and
absence of retired controllers. Release tests inspect real archives and hashes.

The local end-to-end harness creates isolated Git repositories, deliberately
produces a failing test, validates a bounded repair, and runs pytest again to
prove the repaired result. It uses deterministic edits and API fixtures, **not a
live model or a live GitHub publication**. It never damages the application PR.

After infrastructure review/activation, run a fresh owner-approved task (such as
#89 with revised software-only acceptance criteria), then another independently
approved issue without changing controller code. Record actual workflow URLs,
SHA values, generated PRs, full CI and readiness results. A real model repair
cycle is only proven when it actually occurs. Test intentional failures only in
an explicitly authorized disposable test repository; never inject faults into
#108 or a production branch. Keep any unexecuted live stage OPEN in the report.

## Files and release boundary

- `scripts/automation/`: shared authorization, scope, artifact and GitHub logic.
- `scripts/issue_implement.py`, `ci_repair.py`, `ai_merge_readiness.py`: thin generic
  entrypoints; planner/model-router remain reusable and read-only as appropriate.
- `.github/workflows/ai-issue-implement.yml`, `opencode-ci-self-repair.yml`,
  `ai-merge-readiness.yml`: generic orchestration. `ai-automation-tests.yml` replaces
  the three separate issue-specific guard workflows.
- `.opencode/agents/ai-task.md`: deny-by-default template, restricted further by
  the runtime owner scope; no committed per-issue agent.

AI tooling is excluded from release assets created by `scripts/build_release.py`.
Normal build, development and installation helpers are retained. This does not
rewrite already published assets or change GitHub's automatic source archives.
