"""The same controller accepts distinct approved tasks and rejects escalation."""

import copy

import pytest

from .helpers import OWNER, fixture
from automation.approval import authorize, latest_plan
from automation.scope import authorize_task, normalize_scope, safe_path, scope_from_command


@pytest.mark.parametrize("number,version", [(89, 3), (1234, 5), (9999, 1)])
def test_distinct_issues_and_versions_use_identical_code(number, version):
    issue, comments = fixture(number, version)
    result = authorize_task(issue, comments, comments[-1], OWNER, OWNER, expected_issue_number=number)
    assert result["issue_number"] == number
    assert result["version"] == version
    assert result["scope"]["files"] == ["docs/feature.md", "feature.py", "tests/test_feature.py"]


@pytest.mark.parametrize("number", [0, -1, True, "89", None])
def test_invalid_expected_issue(number):
    issue, history = fixture()
    with pytest.raises(ValueError, match="positive issue number"):
        authorize_task(issue, history, history[-1], OWNER, OWNER, expected_issue_number=number)


def test_no_default_issue_or_implicit_write_scope():
    issue, history = fixture()
    with pytest.raises(TypeError, match="expected_issue_number"):
        authorize(issue, history, history[-1], OWNER, OWNER)
    history[-1]["body"] = "/ai implement v3"
    with pytest.raises(ValueError, match="scope is missing"):
        authorize_task(issue, history, history[-1], OWNER, OWNER, expected_issue_number=89)


@pytest.mark.parametrize("actor", ["external", "", "github-actions[bot]"])
def test_only_owner_can_start(actor):
    issue, history = fixture()
    with pytest.raises(ValueError, match="repository owner"):
        authorize_task(issue, history, history[-1], actor, OWNER, expected_issue_number=89)


@pytest.mark.parametrize("change", ["digest", "labels", "waiting", "closed", "other_issue",
                                     "forged_plan", "forged_command", "receipt", "old_version",
                                     "late_approval", "edited_plan", "edited_command", "edited_approval"])
def test_authorization_changes_fail_closed(change):
    issue, history = fixture()
    if change == "digest":
        issue["body"] += " new requirement"
    elif change == "labels":
        issue["labels"] = []
    elif change == "waiting":
        issue["labels"].append({"name": "ai:waiting"})
    elif change == "closed":
        issue["state"] = "closed"
    elif change == "other_issue":
        issue["number"] = 90
    elif change == "forged_plan":
        history[0]["user"]["login"] = "attacker"
    elif change == "forged_command":
        history[-1]["user"]["login"] = "attacker"
    elif change == "receipt":
        history[2]["body"] = "not a receipt"
    elif change == "old_version":
        history[-1]["body"] = history[-1]["body"].replace("v3", "v2")
    elif change == "late_approval":
        history[1]["id"] = 50
    else:
        index = {"edited_plan": 0, "edited_command": -1, "edited_approval": 1}[change]
        history[index]["updated_at"] = "2026-01-02T00:00:00Z"
    with pytest.raises(ValueError):
        authorize_task(issue, history, history[-1], OWNER, OWNER, expected_issue_number=89)


def test_command_must_be_in_live_history_unchanged():
    issue, history = fixture()
    command = copy.deepcopy(history[-1])
    command["body"] += "\nextra"
    with pytest.raises(ValueError, match="live comment history"):
        authorize_task(issue, history, command, OWNER, OWNER, expected_issue_number=89)


def test_newer_questions_invalidate_previous_plan():
    _, history = fixture()
    newer = copy.deepcopy(history[0])
    newer["id"] = 35
    newer["body"] = newer["body"].replace('"plan"', '"questions"')
    history.append(newer)
    with pytest.raises(ValueError, match="questions"):
        latest_plan(history)


@pytest.mark.parametrize("path", ["../evil.py", "/tmp/evil.py", "C:/evil.py", "web_ui\\app.py",
                                  ".github/workflows/ci.yml", "scripts/automation/approval.py",
                                  "opencode.jsonc", "AGENTS.md", "tests/conftest.py",
                                  "tests/test_ai_pipeline.py", "requirements.txt", "tests/*.py",
                                  "web_ui//app.py", "docs/../evil.md", "file.py\n", "setup.py",
                                  "web_ui/.env", "tests/automation/helpers.py"])
def test_privileged_and_nonliteral_paths_are_never_authorized(path):
    with pytest.raises(ValueError):
        safe_path(path)


@pytest.mark.parametrize("scope", [{}, {"files": []}, {"files": ["a.py"]},
                                  {"files": ["README.md", "README.md"]},
                                  {"files": ["README.md"], "create": ["other.md"]},
                                  {"files": ["README.md"], "required": ["other.md"]},
                                  {"files": ["README.md"], "skip_review": True},
                                  {"files": "README.md"}, {"files": [None]}])
def test_malformed_or_unbounded_scope_rejected(scope):
    with pytest.raises(ValueError):
        normalize_scope(scope)


def test_scope_is_data_not_python_or_shell():
    with pytest.raises(ValueError):
        scope_from_command('/ai implement v1\n{"files":["README.md"],"files":["evil.py"]}')
    with pytest.raises(ValueError):
        scope_from_command('/ai implement v1\n__import__("os").system("echo bad")')
    normalized = scope_from_command('/ai implement v1\n{"files":["README.md"]}')
    assert normalized == {"files": ["README.md"], "create": [], "required": []}


def test_file_scope_is_bound_to_exact_owner_command():
    issue, history = fixture()
    first = authorize_task(issue, history, history[-1], OWNER, OWNER, expected_issue_number=89)
    history[-1]["body"] = history[-1]["body"].replace("docs/feature.md", "docs/other.md")
    second = authorize_task(issue, history, history[-1], OWNER, OWNER, expected_issue_number=89)
    assert first["scope_sha256"] != second["scope_sha256"]
    assert first["command_sha256"] != second["command_sha256"]
