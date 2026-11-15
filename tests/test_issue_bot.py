import importlib.util
import json
from pathlib import Path

import pytest


MODULE = Path(__file__).resolve().parents[1] / "scripts" / "issue_bot.py"
SPEC = importlib.util.spec_from_file_location("issue_bot", MODULE)
assert SPEC and SPEC.loader
bot = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bot)


def issue(labels=None, **kwargs):
    return {
        "number": 137,
        "title": "KNX YAML output regression",
        "body": "Preserve old configs",
        "state": "open",
        "labels": [{"name": label} for label in (labels or ["ai:plan", "ai:waiting"])],
        **kwargs,
    }


def state_comment(version=1, kind="plan", original_issue=None, user="github-actions[bot]"):
    old = original_issue or issue()
    data = {"version": version, "kind": kind, "issue_digest": bot.issue_digest(old)}
    return {
        "id": version * 10,
        "user": {"login": user},
        "body": "<!-- knx-issue-bot-state " + json.dumps(data) + " -->\nplan",
    }


def decide(event_name, action, body=None, labels=None, comments=None, actor="diddip21"):
    value = {"action": action, "issue": issue(labels=labels)}
    if event_name == "issues":
        value["label"] = {"name": "ai:plan"}
    else:
        value["comment"] = {"body": body or ""}
    return bot.choose(event_name, value, actor, "diddip21", comments or [])


def test_labeled_issue_triggers_version_one():
    result = decide("issues", "labeled")
    assert result["operation"] == "plan"
    assert result["version"] == 1


def test_reply_increments_version():
    result = decide(
        "issue_comment", "created", "/ai answer Beide Ausgabeformate",
        comments=[state_comment()],
    )
    assert result["operation"] == "plan"
    assert result["version"] == 2
    assert "Beide Ausgabeformate" in result["answer"]


def test_no_automatic_implementation_on_approval():
    result = decide(
        "issue_comment", "created", "/ai approve v1",
        comments=[state_comment()],
    )
    assert result["operation"] == "approve"
    assert "kein Code" in result["comment"]


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("/ai approve v2", "Plan version mismatch"),
        ("/ai approve v1 trailing", "Not an /ai command"),
        ("/ai answer", "Missing answer"),
        ("Please implement this now", "Not an /ai command"),
    ],
)
def test_bad_commands_are_not_executed(message, expected):
    result = decide(
        "issue_comment", "created", message, comments=[state_comment()]
    )
    assert result["operation"] == "noop"
    assert result["reason"] == expected


def test_approval_requires_current_issue_digest():
    changed = issue(body="Changed acceptance criteria")
    event = {"action": "created", "issue": changed, "comment": {"body": "/ai approve v1"}}
    result = bot.choose(
        "issue_comment", event, "diddip21", "diddip21", [state_comment()]
    )
    assert result["operation"] == "notice"


def test_approval_requires_waiting_label():
    result = decide(
        "issue_comment", "created", "/ai approve v1",
        labels=["ai:plan"], comments=[state_comment()],
    )
    assert result["operation"] == "noop"


def test_untrusted_comment_is_not_a_plan_state():
    result = decide(
        "issue_comment", "created", "/ai approve v1",
        comments=[state_comment(user="external-user")],
    )
    assert result["operation"] == "noop"


def test_only_repo_owner_may_trigger():
    result = decide(
        "issue_comment", "created", "/ai approve v1",
        comments=[state_comment()], actor="random-contributor",
    )
    assert result["operation"] == "noop"


def test_pr_events_cannot_trigger():
    event = {"action": "labeled", "label": {"name": "ai:plan"},
             "issue": issue(pull_request={"url": "https://example.com"})}
    result = bot.choose("issues", event, "diddip21", "diddip21", [])
    assert result["operation"] == "noop"


def test_parse_json_response_and_comment():
    d = decide("issues", "labeled")
    output = bot.parse_model_text(json.dumps({
        "kind": "plan",
        "markdown": "## Tests\n\nBitte alle YAML Golden Tests ausführen.",
    }))
    rendered = bot.render_agent_comment(d, output)
    assert "knx-issue-bot-state" in rendered
    assert "/ai approve v1" in rendered


def test_oversized_answer_does_not_trigger_model():
    result = decide(
        "issue_comment", "created", "/ai answer " + "x" * 4001,
        comments=[state_comment()],
    )
    assert result["operation"] == "noop"


def test_questions_cannot_be_approved():
    result = decide(
        "issue_comment", "created", "/ai approve v1",
        comments=[state_comment(kind="questions")],
    )
    assert result["operation"] == "noop"


def test_rendered_comment_has_version_and_digest():
    d = decide("issues", "labeled")
    comment = bot.render_agent_comment(
        d, {"kind": "questions", "markdown": "Soll der Legacy-Export erhalten bleiben?"}
    )
    state = bot.last_bot_state([{
        "id": 1, "user": {"login": "github-actions[bot]"}, "body": comment
    }])
    assert state is not None
    assert state["state"]["version"] == 1
    assert state["state"]["issue_digest"] == bot.issue_digest(issue())


def test_model_text_requires_schema():
    with pytest.raises(ValueError):
        bot.parse_model_text("answer but no structured JSON")
