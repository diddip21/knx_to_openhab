"""Prevent regressions in issue-to-dev workflow cleanup and AI permissions."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"


def workflow(name):
    return (WORKFLOWS / name).read_text(encoding="utf-8")


def test_main_ci_does_not_double_run_on_ai_feature_pushes():
    ci = workflow("ci.yml")
    assert 'branches: ["main", "dev"]' in ci
    assert 'branches: ["**"]' in ci
    assert "workflow_dispatch:" in ci
    assert "Core Tests (Python" in ci
    assert "UI Tests (Playwright)" in ci


def test_completed_pilots_have_no_live_special_controller():
    assert not (WORKFLOWS / "opencode-issue-implement.yml").exists()
    assert not (WORKFLOWS / "opencode-issue89-implement.yml").exists()
    assert not (ROOT / ".opencode/agents/issue-implementer.md").exists()
    assert not (ROOT / "scripts/issue_impl.py").exists()
    assert not (ROOT / "scripts/issue89_impl.py").exists()
    assert (ROOT / "scripts/automation/approval.py").is_file()
    assert (ROOT / "scripts/issue_implement.py").is_file()


def test_all_active_actions_use_repo_approved_major_versions():
    for path in WORKFLOWS.glob("*.yml"):
        text = path.read_text(encoding="utf-8")
        assert "actions/checkout@v4" not in text, path
        assert "actions/setup-node@v4" not in text, path
        assert "actions/upload-artifact@v4" not in text, path
        assert "actions/download-artifact@v4" not in text, path
        assert not re.search(r"uses:\s+\S+@(node12|node16|node20)\b", text), path


def test_cli_is_consistently_pinned_in_every_active_workflow():
    pin = (ROOT / ".github/opencode-cli-version").read_text(encoding="utf-8").strip()
    assert re.fullmatch(r"2\.\d+\.\d+", pin)
    paths = []
    for path in WORKFLOWS.glob("*.yml"):
        content = path.read_text(encoding="utf-8")
        if "npm install" not in content or "@opencode/cli" not in content:
            continue
        paths.append(path.name)
        for line in content.splitlines():
            if "npm install" in line and "@opencode/cli" in line:
                assert "@opencode/cli@$(cat " in line, path
                assert ".github/opencode-cli-version" in line, path
                assert "npm install -g @opencode/cli" not in line, path
    assert set(paths) == {
        "opencode-issue-planner.yml",
        "ai-issue-implement.yml",
        "opencode-ci-self-repair.yml",
        "opencode-model-router-tests.yml",
        "opencode-free-smoke.yml",
    }


def test_merge_readiness_is_trusted_read_only_and_never_checks_out_pr_head():
    text = workflow("ai-merge-readiness.yml")
    assert "pull_request_target:" in text
    assert "workflow_dispatch:" in text
    assert "ref: " + "$" + "{{ github.event.repository.default_branch }}" in text
    assert "pull-requests: read" in text
    assert "checks: read" in text
    assert "contents: read" in text
    assert "persist-credentials: false" in text
    assert "pull-requests: write" not in text
    assert "contents: write" not in text
    assert "createPullRequest" not in text
    assert "merge(" not in text
    assert "pull_request.head.sha }}" not in text
    assert "git checkout" not in text


def test_issue_and_repair_publishing_guards_stay_on_dev():
    implement = workflow("ai-issue-implement.yml")
    repair = workflow("opencode-ci-self-repair.yml")
    publisher = (ROOT / "scripts/automation/github.cjs").read_text(encoding="utf-8")
    assert "head, base: 'dev', draft: true" in publisher
    assert "pr.base.ref !== 'dev'" in publisher
    assert "!pr.draft" in publisher
    assert "workflow_dispatch" in repair
    assert "force: false" in publisher
    assert "createWorkflowDispatch" in publisher
    assert "auto_merge" not in implement + repair + publisher
    assert "pulls.merge" not in publisher
