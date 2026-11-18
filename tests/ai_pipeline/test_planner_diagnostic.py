"""Private planner replays do not replace a live plan or its approval."""

import copy
import json
import subprocess

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


def test_actual_context_fetch_handles_github_context_prototype_getters(tmp_path):
    definition = yaml.safe_load((ROOT / ".github/workflows/ai-planner-diagnostic.yml").read_text())
    step = next(
        s
        for s in definition["jobs"]["diagnose"]["steps"]
        if s.get("name") == "Read current issue and PR context without modifying GitHub"
    )
    harness = r"""
const fs = require('node:fs');
const path = require('node:path');
const AsyncFunction = Object.getPrototypeOf(async function(){}).constructor;
const [script,temp,root] = process.argv.slice(1);
class Context {
  get repo() { return {owner:'owner',repo:'repo'}; }
  get issue() { return {number:125}; }
}
const context = Object.assign(new Context(), {actor:'owner',eventName:'pull_request',
  payload:{pull_request:{body:'AI-Plan-Diagnostic-Issue: 137', user:{login:'owner'},
    head:{repo:{full_name:'owner/repo'}}}}});
const github = {rest:{issues:{get:async()=>({data:{number:137,state:'open',title:'Example',body:''}}),
  listComments:async()=>[]},pulls:{list:async()=>[]}},paginate:async(f,a)=>f(a)};
const load = name => name.endsWith('diagnostic_request.cjs')
  ? require(path.join(root,'scripts/automation/diagnostic_request.cjs'))
  : name.endsWith('planning.cjs') ? require(path.join(root,'scripts/automation/planning.cjs')) : require(name);
new AsyncFunction('require','context','github','process',script)(load,context,github,
  {env:{GITHUB_WORKSPACE:root,RUNNER_TEMP:temp}}).catch(e=>{console.error(e);process.exitCode=1;});
"""
    result = subprocess.run(
        ["node", "-e", harness, step["with"]["script"], str(tmp_path), str(ROOT)],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
    source = json.loads((tmp_path / "planner-diagnostic-source.json").read_text())
    assert source["issue"]["number"] == 137
