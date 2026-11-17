"""Contract tests for generic, trusted-main controllers and isolated dev candidates."""

from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github/workflows"


def workflow(name):
    return (WORKFLOWS / name).read_text(encoding="utf-8")


@pytest.mark.parametrize("name", ["ai-issue-implement.yml", "opencode-ci-self-repair.yml"])
def test_generator_and_publisher_are_separate_and_do_not_merge(name):
    text = workflow(name)
    definition = yaml.safe_load(text)
    generation = "implement" if name == "ai-issue-implement.yml" else "repair"
    assert definition["permissions"] == {}
    assert definition["jobs"]["publish"]["needs"] == generation
    assert all(value == "read" for value in definition["jobs"][generation]["permissions"].values())
    assert definition["jobs"]["publish"]["permissions"]["contents"] == "write"
    assert "python -I ../trusted/scripts/" in text
    assert "task-verified.json" in text
    assert "persist-credentials: true" not in text
    assert "allow-unsafe-pr-checkout: true" not in text
    assert "HEAD:.opencode" in text
    assert "opencode.json opencode.jsonc" in text
    assert "issue-89" not in text and "issue89" not in text
    publisher = (ROOT / "scripts/automation/github.cjs").read_text(encoding="utf-8")
    assert "force: false" in publisher
    assert "head, base: 'dev', draft: true" in publisher
    assert "createWorkflowDispatch" in publisher
    assert "pulls.merge" not in publisher and "autoMerge" not in publisher


def test_implementation_requires_live_owner_scope_on_development_source():
    text = workflow("ai-issue-implement.yml")
    assert "issue_comment:" in text
    assert "github.actor == github.repository_owner" in text
    assert "git merge-base --is-ancestor" in text
    assert "ref: dev" in text
    assert "path: trusted" in text and "path: candidate" in text and "path: target" in text
    assert "issue_implement.py prepare" in text
    assert "issue_implement.py collect" in text
    assert "issue_implement.py recheck" in text


def test_repair_remains_bounded_to_explicit_failed_ci_and_exact_commit():
    text = workflow("opencode-ci-self-repair.yml")
    assert "workflow_run:" in text and 'workflows: ["CI"]' in text
    assert "github.event.workflow_run.event == 'workflow_dispatch'" in text
    assert "github.event.workflow_run.head_repository.full_name == github.repository" in text
    assert "ref: ${{ github.event.workflow_run.head_sha }}" in text
    assert "ci_repair.py recheck" in text
    assert "git restore --source=HEAD --worktree -- .opencode/agents/ai-task.md" in text


def test_readiness_is_read_only_and_reruns_after_ci():
    text = workflow("ai-merge-readiness.yml")
    definition = yaml.safe_load(text)
    assert all(value == "read" for value in definition["permissions"].values())
    assert "workflow_run:" in text
    assert "ref: ${{ github.event.repository.default_branch }}" in text
    assert "ref: ${{ github.event.pull_request.head" not in text
    assert "ref: ${{ github.event.workflow_run.head_sha }}" not in text
    assert "hardware-accepted" not in text


def test_no_special_issue_controllers_or_agents_remain():
    obsolete = [
        "scripts/issue89_impl.py",
        "scripts/issue_impl.py",
        ".github/workflows/opencode-issue89-implement.yml",
        ".github/workflows/opencode-issue-implement.yml",
        ".github/workflows/ai-issue89-guard-tests.yml",
        ".github/workflows/ai-issue-implement-tests.yml",
        ".github/workflows/ai-ci-repair-tests.yml",
        ".opencode/agents/issue89-implementer.md",
        ".opencode/agents/issue89-ci-repair.md",
    ]
    assert not [name for name in obsolete if (ROOT / name).exists()]
    for name in ["issue_implement.py", "ci_repair.py", "ai_merge_readiness.py"]:
        source = (ROOT / "scripts" / name).read_text(encoding="utf-8")
        assert "issue89" not in source and "== 89" not in source
        assert "ISSUE_NUMBER =" not in source


def test_runtime_agent_defaults_to_deny_and_planner_only_proposes_scope():
    agent = (ROOT / ".opencode/agents/ai-task.md").read_text(encoding="utf-8")
    permissions = yaml.safe_load(agent.split("---", 2)[1])["permissions"]
    assert permissions[0] == {"action": "*", "resource": "*", "effect": "deny"}
    assert not any(p["action"] == "edit" and p["effect"] == "allow" for p in permissions)
    planner = (ROOT / ".opencode/agents/issue-planner.md").read_text(encoding="utf-8")
    assert '"files"' in planner and '"create"' in planner and '"required"' in planner


def test_guard_workflow_covers_shared_logic_and_runs_node_tests_without_optional_runtime():
    text = workflow("ai-automation-tests.yml")
    assert '"scripts/automation/**"' in text
    assert '"tests/ai_pipeline/**"' in text
    assert "actions/setup-node@v7" in text
    assert "tests/test_release_automation_exclusions.py" in text


def test_planner_and_shared_application_ci_keep_existing_roles():
    text = workflow("opencode-issue-planner.yml")
    assert "ref: dev" in text and "../trusted/scripts/issue_bot.py prepare" in text
    ci = workflow("ci.yml")
    assert 'python-version: ["3.11", "3.12", "3.13"]' in ci
    assert "--browser=chromium" in ci
    assert 'SAVE_UI_SCREENSHOTS: "1"' in ci
