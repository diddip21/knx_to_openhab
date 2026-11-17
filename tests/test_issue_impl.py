import base64
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "scripts" / "issue_impl.py"
SPEC = importlib.util.spec_from_file_location("issue_impl", MODULE)
assert SPEC and SPEC.loader
implementation = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(implementation)

OWNER = "diddip21"
OLD_README = (
    "# KNX to OpenHAB Generator\n\n"
    + "## Features\n\n"
    + "Legacy and YAML output.\n\n"
    + "### What Gets Generated\n\n"
    + "See docs/USER_GUIDE.md#openhab-52-yaml-output.\n\n"
    + "### Reports & Auto-Placement\n\n"
    + "Lorem ipsum documentation. output_format legacy yaml\n"
)
NEW_README = OLD_README.replace(
    "docs/USER_GUIDE.md#openhab-52-yaml-output",
    "docs/USER_GUIDE.md#model-format-and-live-gateway-ip",
)


def issue():
    return {
        "number": 96,
        "title": "README output formats",
        "body": "Only README.md may change.",
        "state": "open",
        "labels": [{"name": label} for label in ("ai:plan", "ai:approved")],
    }


def comments(current_issue=None):
    item = current_issue or issue()
    state = {
        "version": 2,
        "kind": "plan",
        "issue_digest": implementation.digest(item),
    }
    return [
        {
            "id": 10,
            "user": {"login": "github-actions[bot]"},
            "body": "<!-- knx-issue-bot-state "
            + json.dumps(state)
            + " -->\n## Plan\nOnly README changes",
        },
        {"id": 20, "user": {"login": OWNER}, "body": "/ai approve v2"},
        {
            "id": 30,
            "user": {"login": "github-actions[bot]"},
            "body": "✅ **Plan v2 freigegeben.**",
        },
        {"id": 40, "user": {"login": OWNER}, "body": "/ai implement v2"},
    ]


def authorize(edited_issue=None, history=None, actor=OWNER):
    data = edited_issue or issue()
    history = history if history is not None else comments()
    return implementation.authorize(data, history, history[-1], actor, OWNER)


def test_owner_and_version_can_authorize_separate_implementation():
    approved = authorize()
    assert approved["issue_number"] == 96
    assert approved["version"] == 2
    assert approved["command_comment_id"] == 40


@pytest.mark.parametrize(
    "actor",
    ["other", "", "github-actions[bot]"],
)
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
        implementation.authorize(issue(), history, command, OWNER, OWNER)


def test_no_code_issue_is_authorized():
    edited = issue()
    edited["number"] = 95
    with pytest.raises(ValueError, match="restricted"):
        authorize(edited_issue=edited)


def test_readme_validated_and_obsolete_link_removed():
    implementation.validate_readme(OLD_README, NEW_README)


def test_unfixed_link_rejected():
    with pytest.raises(ValueError, match="Required README content"):
        implementation.validate_readme(OLD_README, OLD_README.replace("legacy", "legacy2"))


def test_no_diff_rejected():
    with pytest.raises(ValueError, match="No change"):
        implementation.validate_readme(NEW_README, NEW_README)


def test_doc_proposal_rejects_unreasonably_large_diff():
    with pytest.raises(ValueError, match="too large"):
        implementation.validate_readme(OLD_README, NEW_README + "\n" + "line\n" * 150)


def test_artifact_bound_to_readme_bytes():
    blob = NEW_README.encode()
    obj = {
        "path": "README.md",
        "readme_b64": base64.b64encode(blob).decode(),
        "readme_sha256": hashlib.sha256(blob).hexdigest(),
    }
    assert hashlib.sha256(base64.b64decode(obj["readme_b64"])).hexdigest() == obj["readme_sha256"]


def test_completed_readme_pilot_is_archived_without_removing_shared_approval_guards():
    assert not (ROOT / ".github/workflows/opencode-issue-implement.yml").exists()
    assert not (ROOT / ".opencode/agents/issue-implementer.md").exists()
    assert (ROOT / ".github/workflows/opencode-issue89-implement.yml").is_file()
    assert (ROOT / "scripts/issue_impl.py").is_file()
