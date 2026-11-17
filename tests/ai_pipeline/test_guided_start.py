"""Owner start commands must stay bound to a reviewed, immutable file scope."""

import json

import pytest

from .helpers import OWNER, fixture, module

bot = module("issue_bot")
from automation.scope import authorize_task, normalize_scope  # noqa: E402


def guided_fixture():
    issue, comments = fixture()
    scope = normalize_scope(
        json.loads(comments[-1]["body"].split("```json\n")[1].split("```", 1)[0])
    )
    marker = json.loads(comments[0]["body"].split("<!-- knx-issue-bot-state ")[1].split(" -->")[0])
    marker["scope"] = scope
    comments[0]["body"] = "<!-- knx-issue-bot-state " + json.dumps(marker) + " -->\nPlan"
    comments[-1]["body"] = "/ai start v3"
    return issue, comments, scope


def test_short_start_uses_only_current_reviewed_scope():
    issue, comments, scope = guided_fixture()
    result = authorize_task(issue, comments, comments[-1], OWNER, OWNER, expected_issue_number=89)
    assert result["scope"] == scope


@pytest.mark.parametrize(
    "attack", ["old_plan", "edited_plan", "no_scope", "unsafe_scope", "extra_text"]
)
def test_short_start_cannot_broaden_or_upgrade_old_approval(attack):
    issue, comments, _ = guided_fixture()
    if attack == "old_plan":
        comments[-1]["body"] = "/ai start v2"
    if attack == "edited_plan":
        comments[0]["updated_at"] = "2026-02-01T00:00:00Z"
    if attack in {"no_scope", "unsafe_scope"}:
        marker = json.loads(
            comments[0]["body"].split("<!-- knx-issue-bot-state ")[1].split(" -->")[0]
        )
        if attack == "no_scope":
            del marker["scope"]
        else:
            marker["scope"]["files"].append("scripts/automation/approval.py")
        comments[0]["body"] = "<!-- knx-issue-bot-state " + json.dumps(marker) + " -->\nPlan"
    if attack == "extra_text":
        comments[-1]["body"] += "\nAlso change other.py"
    with pytest.raises(ValueError):
        authorize_task(issue, comments, comments[-1], OWNER, OWNER, expected_issue_number=89)


def test_approval_receipt_explains_next_action_with_copyable_short_command():
    issue, comments, _ = guided_fixture()
    issue["labels"] = [{"name": "ai:plan"}, {"name": "ai:waiting"}]
    decision = bot.choose(
        "issue_comment",
        {"action": "created", "issue": issue, "comment": {"body": "/ai approve v3"}},
        OWNER,
        OWNER,
        comments[:1],
    )
    assert decision["operation"] == "approve"
    assert "/ai start v3" in decision["comment"]
    assert "Dateiumfang" in decision["comment"]


def test_planner_publishes_only_valid_scope_and_displays_it():
    response = bot.parse_model_text(
        json.dumps(
            {
                "kind": "plan",
                "markdown": "A sufficiently detailed plan.",
                "scope": {"files": ["README.md"], "create": [], "required": []},
            }
        )
    )
    rendered = bot.render_agent_comment({"version": 4, "digest": "a" * 64}, response)
    assert '"scope"' in rendered
    assert "README.md" in rendered
    with pytest.raises(ValueError):
        bot.parse_model_text(
            json.dumps(
                {
                    "kind": "plan",
                    "markdown": "A sufficiently detailed plan.",
                    "scope": {"files": [".github/workflows/ci.yml"]},
                }
            )
        )
