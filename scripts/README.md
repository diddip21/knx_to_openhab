# Repository scripts

Application/build helpers such as `build_release.py`, golden-output generators,
and `dev-*` / `verify-setup` scripts remain here.

The generic AI workflow uses `automation/` for shared authorization, scope,
artifact validation and GitHub publication. Its entrypoints are
`issue_implement.py`, `ci_repair.py` and `ai_merge_readiness.py`. Planning and
free-model selection use `issue_bot.py` and `opencode_model_router.py`.

The #89/#96 pilot executables and fixed feature agents are retired. Test cases
may name those issues, but production behavior does not depend on their numbers.
A future approved task needs a reviewed plan and explicit owner file scope, not
another script or workflow. No generic unrestricted writer or auto-merge exists.

See [the workflow runbook](../docs/AI_AUTOMATION.md) for command syntax,
authorization boundaries, activation, test evidence and remaining live checks.
AI tooling is versioned for review, but excluded from generated application
release assets. General build/development helpers are not excluded wholesale.
