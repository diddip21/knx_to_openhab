# Archived README implementation pilot

The README-only experiment for issue #96 and PR #100 is complete. Its dedicated
workflow, agent, executable controller and tests have been retired. The old
implementation remains available in Git history; it is not an active way to
start work or grant file access.

Reusable owner, plan and issue-digest checks now live in
`scripts/automation/approval.py`; explicit task file scopes are validated in
`scripts/automation/scope.py`. Neither module is restricted to an individual
issue. The former `scripts/issue_impl.py` compatibility module has also been
removed.

Use [AI_AUTOMATION.md](AI_AUTOMATION.md) for the current generic workflow,
activation prerequisites, owner commands, bounded repairs and software-readiness
report. A historical approval or an old scope-less `/ai implement vN` command
never grants implicit write access under the new protocol.
