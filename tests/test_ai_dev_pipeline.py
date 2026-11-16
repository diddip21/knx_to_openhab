"""Cross-workflow contract tests for main(default) -> dev -> manual main release.

These intentionally verify the *trusted* workflow contracts, not live GitHub
branch synchronization, CI status or hardware review.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WF = ROOT / ".github" / "workflows"


def workflow(name: str) -> str:
    return (WF / name).read_text(encoding="utf-8")


def test_planner_uses_dev_code_but_trusted_main_controller():
    text = workflow("opencode-issue-planner.yml")
    assert "ref: dev" in text
    assert "path: candidate" in text
    assert "path: trusted" in text
    assert "git merge-base --is-ancestor" in text
    assert "../trusted/scripts/issue_bot.py prepare" in text
    assert "../trusted/scripts/issue_bot.py finish" in text
    assert "../trusted/scripts/opencode_model_router.py" in text
    assert "cmp -s" in text
    assert "issue-planner.md" in text


def test_homekit_implementer_uses_dev_for_source_and_pr_base():
    text = workflow("opencode-issue89-implement.yml")
    assert "ref: dev" in text
    assert "path: candidate" in text
    assert "path: target" in text
    assert "path: trusted" in text
    assert "git merge-base --is-ancestor" in text
    assert "../trusted/scripts/issue89_impl.py prepare" in text
    assert "../trusted/scripts/issue89_impl.py collect" in text
    assert "../trusted/scripts/issue89_impl.py recheck" in text
    assert "../trusted/scripts/opencode_model_router.py" in text
    assert "base: 'dev', draft: true" in text
    assert "branch: 'dev'" in text
    assert "base: context.payload.repository.default_branch, draft: true" not in text
    assert "comparison.behind_by !== 0" in text
    assert ".github/workflows/ci.yml" in text
    assert "Require approved CI definition" in text
    assert "actions.createWorkflowDispatch" in text


def test_repair_only_updates_approved_dev_drafts_without_auto_merge():
    text = workflow("opencode-ci-self-repair.yml")
    assert text.count("p.base.ref === 'dev'") == 2
    assert "currentPr.base.ref !== 'dev'" in text
    assert "force:false" in text
    assert "workflow_id:'ci.yml'" in text
    assert "auto_merge" not in text
    check = (ROOT / "scripts" / "ci_repair.py").read_text(encoding="utf-8")
    assert 'get("ref") != "dev"' in check
    assert 'get("ref") != "main"' not in check


def test_default_branch_keeps_workflow_run_and_issue_comment_triggers():
    assert "workflow_run:" in workflow("opencode-ci-self-repair.yml")
    assert "issue_comment:" in workflow("opencode-issue-planner.yml")
    assert "issue_comment:" in workflow("opencode-issue89-implement.yml")


def test_source_and_review_gates_remain_separate():
    impl = workflow("opencode-issue89-implement.yml")
    repair = workflow("opencode-ci-self-repair.yml")
    assert "needs: implement" in impl
    assert "needs: repair" in repair
    assert "pull-requests: write" in impl
    assert "contents: read" in repair
    assert "draft: true" in impl
    assert "createWorkflowDispatch" in impl
    assert "createWorkflowDispatch" in repair


def test_shared_ci_preserves_development_validation_and_evidence():
    text = workflow("ci.yml")
    assert 'python-version: ["3.11", "3.12", "3.13"]' in text
    assert 'SAVE_UI_SCREENSHOTS: "1"' in text
    assert "--browser=chromium" in text
    assert "--screenshot=only-on-failure" in text
    assert "--video=retain-on-failure" in text
    assert "--tracing=retain-on-failure" in text
    assert 'branches: ["**"]' in text
