"""Private planner replays do not replace a live plan or its approval."""

import copy
import json

import pytest
import yaml

from .helpers import ROOT, module

diagnostic = module("automation/planner_diagnostic")
bot = module("issue_bot")


def test_replay_keeps_approved_input_immutable_and_uses_production_prompt(tmp_path):
    issue = {
        "number": 137,
        "state": "open",
        "title": "Workflow example",
        "body": "Keep settings",
        "labels": [{"name": "ai:approved"}],
    }
    marker = {
        "version": 6,
        "kind": "plan",
        "issue_digest": bot.issue_digest(issue),
        "scope": {"files": ["README.md"], "create": [], "required": []},
    }
    source = {
        "issue": issue,
        "comments": [
            {
                "id": 10,
                "user": {"login": "github-actions[bot]"},
                "body": "<!-- knx-issue-bot-state " + json.dumps(marker) + " -->\nCurrent plan",
            }
        ],
        "related": {"pull_requests": []},
    }
    original = copy.deepcopy(source)
    diagnostic.prepare(source, tmp_path, bot)
    assert source == original
    decision = json.loads((tmp_path / "issue-decision.json").read_text())
    assert decision["version"] == 6
    assert decision["digest"] == bot.issue_digest(issue)
    assert "Current plan" in decision["previous"]
    assert (tmp_path / "issue-prompt.txt").read_text(encoding="utf-8") == bot.make_prompt(decision)
    assert not (tmp_path / "issue-result.json").exists()


@pytest.mark.parametrize("change", [{"state": "closed"}, {"pull_request": {"url": "example"}}])
def test_private_replay_rejects_wrong_target(tmp_path, change):
    with pytest.raises(ValueError, match="open issue"):
        diagnostic.prepare({"issue": {"state": "open", **change}}, tmp_path, bot)


def test_live_diagnostic_has_no_github_write_or_publisher_and_exports_only_metrics():
    workflow = (ROOT / ".github/workflows/ai-planner-diagnostic.yml").read_text()
    definition = yaml.safe_load(workflow)
    assert all(value == "read" for value in definition["permissions"].values())
    assert "github.actor == github.repository_owner" in workflow
    assert "git merge-base --is-ancestor" in workflow
    assert "../trusted/scripts/opencode_model_router.py" in workflow
    assert "publish" not in definition["jobs"]
    for step in definition["jobs"]["diagnose"]["steps"]:
        if step.get("uses", "").startswith("actions/checkout"):
            assert step["with"]["persist-credentials"] is False
        if step.get("uses", "").startswith("actions/upload-artifact"):
            assert set(step["with"]["path"].splitlines()) == {
                "${{ runner.temp }}/planner-diagnostics.json",
                "${{ runner.temp }}/model-router.json",
            }
    script = (ROOT / "scripts/automation/planner_diagnostic.py").read_text()
    assert 'import_module("automation.planner_runner")' in script
    assert "runner.run_plan" in script
