"""Shared approval checks survive retirement of the issue #96 README pilot."""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
SPEC = importlib.util.spec_from_file_location("issue_impl", ROOT / "scripts/issue_impl.py")
assert SPEC and SPEC.loader
implementation = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(implementation)

OWNER = "diddip21"
ISSUE_NUMBER = 123


def issue(number=ISSUE_NUMBER):
    return {
        "number": number,
        "title": "A separately approved task",
        "body": "The controller supplies the trusted scope.",
        "state": "open",
        "labels": [{"name": label} for label in ("ai:plan", "ai:approved")],
    }


def comments(current_issue=None):
    item = current_issue or issue()
    state = {"version": 2, "kind": "plan", "issue_digest": implementation.digest(item)}
    return [
        {
            "id": 10,
            "user": {"login": "github-actions[bot]"},
            "body": "<!-- knx-issue-bot-state " + json.dumps(state) + " -->\nPlan",
        },
        {"id": 20, "user": {"login": OWNER}, "body": "/ai approve v2"},
        {
            "id": 30,
            "user": {"login": "github-actions[bot]"},
            "body": "\u2705 **Plan v2 freigegeben.**",
        },
        {"id": 40, "user": {"login": OWNER}, "body": "/ai implement v2"},
    ]


def authorize(edited_issue=None, history=None, actor=OWNER):
    data = edited_issue or issue()
    history = history if history is not None else comments()
    return implementation.authorize(
        data, history, history[-1], actor, OWNER, expected_issue_number=ISSUE_NUMBER
    )


@pytest.mark.parametrize("number", [89, 96, 123, 9999])
def test_approval_helper_is_reusable_with_explicit_trusted_issue(number):
    item = issue(number)
    history = comments(item)
    approved = implementation.authorize(
        item, history, history[-1], OWNER, OWNER, expected_issue_number=number
    )
    assert approved["issue_number"] == number
    assert approved["version"] == 2
    assert approved["command_comment_id"] == 40


def test_no_implicit_issue96_default():
    history = comments()
    with pytest.raises(TypeError, match="expected_issue_number"):
        implementation.authorize(issue(), history, history[-1], OWNER, OWNER)


@pytest.mark.parametrize("number", [0, -1, True, "123", None])
def test_invalid_trusted_issue_rejected(number):
    history = comments()
    with pytest.raises(ValueError, match="positive issue number"):
        implementation.authorize(
            issue(), history, history[-1], OWNER, OWNER, expected_issue_number=number
        )


@pytest.mark.parametrize("actor", ["other", "", "github-actions[bot]"])
def test_only_owner_can_initiate(actor):
    with pytest.raises(ValueError, match="repository owner"):
        authorize(actor=actor)


def test_missing_approval_label_cannot_publish():
    edited = issue()
    edited["labels"] = [{"name": "ai:plan"}]
    with pytest.raises(ValueError, match="not approved"):
        authorize(edited_issue=edited)


def test_waiting_issue_cannot_publish():
    edited = issue()
    edited["labels"].append({"name": "ai:waiting"})
    with pytest.raises(ValueError, match="not approved"):
        authorize(edited_issue=edited)


def test_modified_issue_digest_is_rejected():
    edited = issue()
    edited["body"] = "The scope changed after plan approval."
    with pytest.raises(ValueError, match="stale"):
        authorize(edited_issue=edited)


def test_approval_of_old_version_is_rejected():
    history = comments()
    history[-1]["body"] = "/ai implement v1"
    with pytest.raises(ValueError, match="stale"):
        authorize(history=history)


def test_approval_after_implementation_command_is_rejected():
    history = comments()
    history[1]["id"] = 50
    with pytest.raises(ValueError, match="owner approval"):
        authorize(history=history)


def test_missing_bot_confirmation_is_rejected():
    history = comments()
    history[2]["body"] = "some other message"
    with pytest.raises(ValueError, match="not confirmed"):
        authorize(history=history)


def test_forged_plan_comment_is_rejected():
    history = comments()
    history[0]["user"]["login"] = "another-user"
    with pytest.raises(ValueError, match="No trusted"):
        authorize(history=history)


def test_forged_command_comment_is_rejected():
    history = comments()
    history[-1]["user"]["login"] = "another-user"
    with pytest.raises(ValueError, match="authored by the owner"):
        authorize(history=history)


def test_command_not_in_history_is_rejected():
    history = comments()
    command = dict(history[-1], id=999)
    with pytest.raises(ValueError, match="not in the live"):
        implementation.authorize(
            issue(), history, command, OWNER, OWNER, expected_issue_number=ISSUE_NUMBER
        )


def test_issue_cannot_select_another_trusted_scope():
    edited = issue(ISSUE_NUMBER + 1)
    with pytest.raises(ValueError, match="restricted"):
        authorize(edited_issue=edited)


@pytest.mark.parametrize("change", [{"state": "closed"}, {"pull_request": {"url": "PR"}}])
def test_only_open_issues_are_eligible(change):
    edited = issue() | change
    with pytest.raises(ValueError, match="open issue"):
        authorize(edited_issue=edited)


def test_newer_plan_invalidates_older_approval():
    history = comments()
    history.insert(3, dict(history[0], id=35))
    with pytest.raises(ValueError, match="owner approval"):
        authorize(history=history)


def test_compatibility_facade_uses_the_shared_implementation():
    from automation.approval import authorize as shared_authorize
    from automation.git_helpers import git

    assert implementation.authorize is shared_authorize
    assert implementation.git is git
    assert not hasattr(implementation, "validate_readme")
    assert not hasattr(implementation, "prepare")
    assert not hasattr(implementation, "collect")
    assert not hasattr(implementation, "recheck")
    assert not hasattr(implementation, "ISSUE_NUMBER")


@pytest.mark.parametrize("command", ["prepare", "collect", "recheck"])
def test_retired_readme_cli_fails_without_writes(tmp_path, command):
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/issue_impl.py"), command],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "retired" in result.stderr
    assert list(tmp_path.iterdir()) == []


def test_completed_readme_pilot_is_archived_without_removing_shared_approval_guards():
    assert not (ROOT / ".github/workflows/opencode-issue-implement.yml").exists()
    assert not (ROOT / ".opencode/agents/issue-implementer.md").exists()
    assert (ROOT / ".github/workflows/opencode-issue89-implement.yml").is_file()
    assert (ROOT / "scripts/automation/approval.py").is_file()
    assert (ROOT / "scripts/issue_impl.py").is_file()


@pytest.mark.parametrize(
    "workflow",
    ["ai-issue-implement-tests.yml", "ai-issue89-guard-tests.yml", "ai-ci-repair-tests.yml"],
)
def test_shared_approval_changes_trigger_all_dependent_guards(workflow):
    text = (ROOT / ".github/workflows" / workflow).read_text(encoding="utf-8")
    assert '"scripts/automation/**"' in text
    assert '"scripts/issue_impl.py"' in text
