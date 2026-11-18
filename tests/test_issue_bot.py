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
        "issue_comment",
        "created",
        "/ai answer Beide Ausgabeformate",
        comments=[state_comment()],
    )
    assert result["operation"] == "plan"
    assert result["version"] == 2
    assert "Beide Ausgabeformate" in result["answer"]


def test_make_prompt_rejects_issue_body_that_would_be_truncated():
    decision = decide("issues", "labeled")
    decision["issue"]["body"] = "x" * (bot.MAX_ISSUE_CHARS + 1)

    with pytest.raises(ValueError, match="shorten the issue before requesting an AI plan"):
        bot.make_prompt(decision)


def test_no_automatic_implementation_on_approval():
    result = decide(
        "issue_comment",
        "created",
        "/ai approve v1",
        comments=[state_comment()],
    )
    assert result["operation"] == "approve"
    assert "kein Code" in result["comment"]
    assert result["digest"] == bot.issue_digest(issue())


def test_prepare_preserves_digest_for_live_approval_check(tmp_path, monkeypatch):
    event = {
        "action": "created",
        "issue": issue(),
        "comment": {"body": "/ai approve v1"},
    }
    (tmp_path / "issue-comments.json").write_text(json.dumps([state_comment()]), encoding="utf-8")
    event_path = tmp_path / "event.json"
    event_path.write_text(json.dumps(event), encoding="utf-8")
    output_path = tmp_path / "github-output.txt"
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event_path))
    monkeypatch.setenv("GITHUB_EVENT_NAME", "issue_comment")
    monkeypatch.setenv("GITHUB_ACTOR", "diddip21")
    monkeypatch.setenv("GITHUB_REPOSITORY_OWNER", "diddip21")
    monkeypatch.setenv("GITHUB_OUTPUT", str(output_path))

    bot.prepare(tmp_path)

    result = json.loads((tmp_path / "issue-result.json").read_text(encoding="utf-8"))
    assert result["digest"] == bot.issue_digest(issue())


def test_prepare_writes_invalidation_for_edited_issue(tmp_path, monkeypatch):
    edited_issue = issue(labels=["ai:plan", "ai:approved"], body="Changed acceptance criteria")
    event = {"action": "edited", "issue": edited_issue}
    (tmp_path / "issue-comments.json").write_text(json.dumps([state_comment()]), encoding="utf-8")
    event_path = tmp_path / "event.json"
    event_path.write_text(json.dumps(event), encoding="utf-8")
    output_path = tmp_path / "github-output.txt"
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event_path))
    monkeypatch.setenv("GITHUB_EVENT_NAME", "issues")
    monkeypatch.setenv("GITHUB_ACTOR", "issue-editor")
    monkeypatch.setenv("GITHUB_REPOSITORY_OWNER", "diddip21")
    monkeypatch.setenv("GITHUB_OUTPUT", str(output_path))

    bot.prepare(tmp_path)

    result = json.loads((tmp_path / "issue-result.json").read_text(encoding="utf-8"))
    assert result["operation"] == "invalidate"
    assert result["digest"] == bot.issue_digest(edited_issue)
    assert result["approved_digest"] == bot.issue_digest(issue())


def test_finish_preserves_digest_for_live_plan_check(tmp_path):
    decision = decide("issues", "labeled")
    (tmp_path / "issue-decision.json").write_text(json.dumps(decision), encoding="utf-8")
    model_response = {
        "kind": "plan",
        "markdown": "## Prüfen\n\nKonfiguration validieren.",
        "scope": {"files": ["README.md"], "create": [], "required": []},
    }
    event = {"type": "text", "part": {"text": json.dumps(model_response)}}
    (tmp_path / "opencode-events.jsonl").write_text(json.dumps(event) + "\n", encoding="utf-8")

    bot.finish(tmp_path)

    result = json.loads((tmp_path / "issue-result.json").read_text(encoding="utf-8"))
    assert result["digest"] == bot.issue_digest(issue())


def test_publish_workflow_revalidates_live_issue_digest_before_label_changes():
    workflow = (
        Path(__file__).resolve().parents[1] / ".github" / "workflows" / "opencode-issue-planner.yml"
    ).read_text(encoding="utf-8")
    publication = workflow[workflow.index("- name: Publish plan, questions or approval") :]
    digest_check = publication.index("liveDigest = crypto.createHash('sha256')")
    approval_label = publication.index("labels: ['ai:approved']")
    waiting_label = publication.index("labels: ['ai:waiting']")

    assert "details.data.title ?? ''" in workflow
    assert "details.data.body ?? ''" in workflow
    assert "liveDigest !== result.digest" in workflow
    assert "liveDigest === result.approved_digest" in workflow
    assert "['approve', 'invalidate', 'plan'].includes(result.operation)" in workflow
    assert digest_check < approval_label
    assert digest_check < waiting_label


def test_plan_comment_is_published_before_label_state_changes():
    workflow = (
        Path(__file__).resolve().parents[1] / ".github" / "workflows" / "opencode-issue-planner.yml"
    ).read_text(encoding="utf-8")
    plan_start = workflow.index("} else if (result.operation === 'plan') {")
    plan_end = workflow.index("} else if (result.operation === 'invalidate')", plan_start)
    plan_publish = workflow[plan_start:plan_end]

    assert plan_publish.index("issues.createComment") < plan_publish.index("issues.addLabels")


def test_workflow_runs_issue_edits_and_leaves_command_parsing_to_controller():
    workflow = (
        Path(__file__).resolve().parents[1] / ".github" / "workflows" / "opencode-issue-planner.yml"
    ).read_text(encoding="utf-8")

    assert "types: [labeled, edited]" in workflow
    assert "contains(github.event.issue.labels.*.name, 'ai:approved')" in workflow
    assert "steps.decision.outputs.operation == 'invalidate'" in workflow
    assert "startsWith(github.event.comment.body" not in workflow


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
    result = decide("issue_comment", "created", message, comments=[state_comment()])
    assert result["operation"] == "noop"
    assert result["reason"] == expected


@pytest.mark.parametrize(
    ("message", "expected_operation"),
    [
        ("/AI approve v1", "approve"),
        ("  /ai approve v1  ", "approve"),
        (" /AI answer Include legacy output", "plan"),
    ],
)
def test_owner_commands_follow_trimmed_case_insensitive_grammar(message, expected_operation):
    result = decide("issue_comment", "created", message, comments=[state_comment()])

    assert result["operation"] == expected_operation


def test_approval_requires_current_issue_digest():
    changed = issue(body="Changed acceptance criteria")
    event = {"action": "created", "issue": changed, "comment": {"body": "/ai approve v1"}}
    result = bot.choose("issue_comment", event, "diddip21", "diddip21", [state_comment()])
    assert result["operation"] == "notice"


def test_issue_edit_invalidates_stale_approval_even_for_non_owner():
    edited = issue(labels=["ai:plan", "ai:approved"], body="Changed acceptance criteria")
    event = {"action": "edited", "issue": edited}

    result = bot.choose("issues", event, "issue-editor", "diddip21", [state_comment()])

    assert result["operation"] == "invalidate"
    assert result["digest"] == bot.issue_digest(edited)
    assert result["approved_digest"] == bot.issue_digest(issue())


def test_issue_edit_keeps_approval_when_digest_still_matches():
    approved = issue(labels=["ai:plan", "ai:approved"])
    event = {"action": "edited", "issue": approved}

    result = bot.choose("issues", event, "issue-editor", "diddip21", [state_comment()])

    assert result["operation"] == "noop"
    assert result["reason"] == "Approved plan still matches issue"


def test_issue_edit_without_approval_is_a_noop():
    edited = issue(labels=["ai:plan", "ai:waiting"], body="Changed acceptance criteria")
    event = {"action": "edited", "issue": edited}

    result = bot.choose("issues", event, "issue-editor", "diddip21", [state_comment()])

    assert result["operation"] == "noop"


def test_approval_requires_waiting_label():
    result = decide(
        "issue_comment",
        "created",
        "/ai approve v1",
        labels=["ai:plan"],
        comments=[state_comment()],
    )
    assert result["operation"] == "noop"


def test_untrusted_comment_is_not_a_plan_state():
    result = decide(
        "issue_comment",
        "created",
        "/ai approve v1",
        comments=[state_comment(user="external-user")],
    )
    assert result["operation"] == "noop"


def test_only_repo_owner_may_trigger():
    result = decide(
        "issue_comment",
        "created",
        "/ai approve v1",
        comments=[state_comment()],
        actor="random-contributor",
    )
    assert result["operation"] == "noop"


def test_pr_events_cannot_trigger():
    event = {
        "action": "labeled",
        "label": {"name": "ai:plan"},
        "issue": issue(pull_request={"url": "https://example.com"}),
    }
    result = bot.choose("issues", event, "diddip21", "diddip21", [])
    assert result["operation"] == "noop"


def test_parse_json_response_and_comment():
    d = decide("issues", "labeled")
    output = bot.parse_model_text(
        json.dumps(
            {
                "kind": "plan",
                "markdown": "## Tests\n\nBitte alle YAML Golden Tests ausführen.",
            }
        )
    )
    rendered = bot.render_agent_comment(d, output)
    assert "knx-issue-bot-state" in rendered
    assert "/ai approve v1" in rendered


def test_oversized_answer_does_not_trigger_model():
    result = decide(
        "issue_comment",
        "created",
        "/ai answer " + "x" * 4001,
        comments=[state_comment()],
    )
    assert result["operation"] == "noop"


def test_questions_cannot_be_approved():
    result = decide(
        "issue_comment",
        "created",
        "/ai approve v1",
        comments=[state_comment(kind="questions")],
    )
    assert result["operation"] == "noop"


def test_rendered_comment_has_version_and_digest():
    d = decide("issues", "labeled")
    comment = bot.render_agent_comment(
        d, {"kind": "questions", "markdown": "Soll der Legacy-Export erhalten bleiben?"}
    )
    state = bot.last_bot_state(
        [{"id": 1, "user": {"login": "github-actions[bot]"}, "body": comment}]
    )
    assert state is not None
    assert state["state"]["version"] == 1
    assert state["state"]["issue_digest"] == bot.issue_digest(issue())


def test_model_text_requires_schema():
    with pytest.raises(ValueError):
        bot.parse_model_text("answer but no structured JSON")


@pytest.mark.parametrize("markdown", [" " * 20, "x" + " " * 19])
def test_model_plan_minimum_length_uses_normalized_markdown(markdown):
    response = json.dumps({"kind": "plan", "markdown": markdown})

    with pytest.raises(ValueError, match="markdown_too_short"):
        bot.parse_model_text(response)


def test_model_plan_is_stripped_before_publication():
    markdown = "  " + "x" * 20 + "  "
    response = json.dumps({"kind": "plan", "markdown": markdown})

    assert bot.parse_model_text(response) == {"kind": "plan", "markdown": "x" * 20}


def test_provider_error_event_is_not_misreported_as_invalid_json(tmp_path):
    events = tmp_path / "events.jsonl"
    events.write_text(
        json.dumps({"type": "error", "error": {"message": "provider-private-detail"}}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="provider_error") as caught:
        bot.read_model_events(events)

    assert "provider-private-detail" not in str(caught.value)


def test_non_object_events_do_not_crash_the_response_reader(tmp_path):
    events = tmp_path / "events.jsonl"
    events.write_text(
        "[]\nnull\n" + json.dumps({"type": "text", "part": {"text": "answer"}}),
        encoding="utf-8",
    )

    assert bot.read_model_events(events) == "answer"


def test_oversized_markdown_reports_the_actual_length():
    response = json.dumps({"kind": "plan", "markdown": "x" * 16001})

    with pytest.raises(ValueError, match="markdown_too_long.*16001"):
        bot.parse_model_text(response)


def test_json_with_an_unrelated_root_cannot_smuggle_a_nested_plan():
    response = json.dumps({"payload": {"kind": "plan", "markdown": "x" * 30}})

    with pytest.raises(ValueError, match="invalid_schema"):
        bot.parse_model_text(response)


def test_new_plan_prompt_states_markdown_limit():
    assert "16000" in bot.make_prompt(decide("issues", "labeled"))


def test_approval_refuses_an_old_plan_after_a_failed_replanning_request():
    comments = [
        state_comment(),
        {"id": 11, "user": {"login": "diddip21"}, "body": "/ai answer Compare existing PRs"},
    ]

    result = decide("issue_comment", "created", "/ai approve v1", comments=comments)

    assert result["operation"] == "notice"
    assert "Neuplanung" in result["comment"]


def test_label_retry_preserves_pending_owner_guidance():
    comments = [
        state_comment(),
        {"id": 11, "user": {"login": "diddip21"}, "body": "/ai answer Compare existing PRs"},
    ]

    result = decide("issues", "labeled", comments=comments)

    assert result["answer"] == "Compare existing PRs"


def test_prepare_binds_plan_publication_to_current_request_and_previous_plan(tmp_path, monkeypatch):
    previous = state_comment()
    comment = {"id": 11, "user": {"login": "diddip21"}, "body": "/ai answer Compare PRs"}
    event_path = tmp_path / "event.json"
    event_path.write_text(json.dumps({"action": "created", "issue": issue(), "comment": comment}))
    (tmp_path / "issue-comments.json").write_text(json.dumps([previous, comment]))
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event_path))
    monkeypatch.setenv("GITHUB_EVENT_NAME", "issue_comment")
    monkeypatch.setenv("GITHUB_ACTOR", "diddip21")
    monkeypatch.setenv("GITHUB_REPOSITORY_OWNER", "diddip21")
    monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path / "output"))

    bot.prepare(tmp_path)

    snapshot = json.loads((tmp_path / "issue-decision.json").read_text())["planning_snapshot"]
    assert snapshot["previous_plan_id"] == 10
    assert snapshot["trigger_comment_id"] == snapshot["latest_answer_id"] == 11
    assert snapshot["trigger_comment_sha256"] == snapshot["latest_answer_sha256"]
    assert len(snapshot["previous_plan_sha256"]) == 64
