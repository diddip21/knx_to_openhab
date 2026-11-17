# Script responsibilities and lifecycle

These files have different lifetimes. Repository automation is versioned here
for review and reproducible CI; it is not part of the installed application.

## Application and development support

`build_release.py` builds the release archive and checksum. The `dev-*` and
`verify-setup.*` scripts support local development and installation checks.
`generate_golden_files.py` and `regenerate_golden.py` maintain regression
fixtures. They are not tied to one issue and remain in place.

## Shared automation

`automation/approval.py` contains the reusable owner/plan/digest checks.
`automation/git_helpers.py` contains the shared Git command helper. The approval
API requires an explicit `expected_issue_number` supplied by a trusted
controller: there is no implicit issue #96 and no automatic write permission.

`issue_impl.py` is now only a compatibility import facade for existing callers.
Its old README prompt, artifact validator and prepare/collect/recheck command
line have been removed. Calling that retired CLI fails without creating files.
The removed implementation remains available in Git history.

The existing `issue_bot.py` (planning), `opencode_model_router.py` (model
selection), and `ai_merge_readiness.py` (read-only report) retain their entry
points. Readiness is still scoped to the project's AI branch convention and
contains issue-specific evidence policy; it is not a universal PR auditor.

## Active, issue-specific pilot

`issue89_impl.py` and `ci_repair.py`, their agent definitions and their live
workflows remain the **issue #89 / plan v2 pilot**. In particular, `ci_repair.py`
is not a general repair service. Its Draft-PR, `dev`, current-commit, file
allowlist and two-attempt limits remain unchanged.

The pilot is kept separate from the reusable approval library, but its existing
file paths are intentionally stable while the HomeKit PR is active. Do not
copy these controllers into another issue-numbered implementation. A future
general executor needs reviewed policies from trusted repository code,
explicit owner authorization, and independent publisher revalidation first.
This cleanup does not activate such an executor or expand any agent's scope.
After the pilot is retired, remove its workflows, agents and controller tests
in one reviewed change; keep the shared approval/security tests.

## Release boundary

`build_release.py` excludes `.github/`, `.opencode/`, `.superpowers/`, root
OpenCode configuration, `scripts/automation/`, and the six existing AI
controller entry points from generated release archives. It does not exclude
all of `scripts/`: application, build and local development helpers stay.
This affects newly built release assets, not Git clones or GitHub's automatic
source archives. Existing published assets are not rewritten.

Add new repository-only controller code under `scripts/automation/` so it is
excluded by directory rather than growing a list for each future issue.
Keep user/runtime scripts outside that directory.

## Verification

The shared approval tests still reject non-owners, changed scopes, stale plans,
missing confirmations, mismatched issues and forged commands. All three
related guard workflows watch `scripts/automation/**` and the compatibility
facade. The real CI-repair fixture includes the shared package when copying
the trusted controller checkout.

Release tests build real archives through both the Git index and an explicit
file list, inspect the contents, check the SHA-256 sidecar and check identical
bytes across repeat builds. Runtime helpers must remain present while AI
controllers must be absent.

```sh
python -m pytest tests/test_issue_impl.py tests/test_issue89_impl.py tests/test_ci_repair.py tests/test_ai_merge_readiness.py tests/test_release_automation_exclusions.py -q -o addopts=
```

The ordinary full CI, review requirements and manual merge decision still
apply. No application/UI behavior, issue approval history or live PR branch is
changed by this cleanup.
