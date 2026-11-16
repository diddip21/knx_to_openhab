"""Security tests for the owner-approved issue #89 coding pilot."""

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
FILE = ROOT / "scripts" / "issue89_impl.py"
SPEC = importlib.util.spec_from_file_location("issue89_impl", FILE)
assert SPEC and SPEC.loader
implementation = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(implementation)

OWNER = "diddip21"


def issue():
    return {
        "number": 89,
        "title": "HomeKit blinds",
        "body": "Only the owner-approved v2 scope.",
        "state": "open",
        "labels": [{"name": "ai:plan"}, {"name": "ai:approved"}],
    }


def comments(item=None):
    item = item or issue()
    marker = {
        "version": 2,
        "kind": "plan",
        "issue_digest": implementation.digest(item),
    }
    return [
        {
            "id": 100,
            "user": {"login": "github-actions[bot]"},
            "body": "<!-- knx-issue-bot-state " + json.dumps(marker) + " -->\nPlan v2",
        },
        {"id": 200, "user": {"login": OWNER}, "body": "/ai approve v2"},
        {
            "id": 300,
            "user": {"login": "github-actions[bot]"},
            "body": "\u2705 **Plan v2 freigegeben.**",
        },
        {"id": 400, "user": {"login": OWNER}, "body": "/ai implement v2"},
    ]


def test_approved_issue89_can_be_authorized():
    history = comments()
    context = implementation.authorize(
        issue(), history, history[-1], OWNER, OWNER, expected_issue_number=89
    )
    assert context["issue_number"] == 89
    assert context["version"] == 2


@pytest.mark.parametrize("number", [96, 90, 0])
def test_other_issues_cannot_use_issue89_scope(number):
    item = issue()
    item["number"] = number
    history = comments(item)
    with pytest.raises(ValueError, match="restricted to issue #89"):
        implementation.authorize(item, history, history[-1], OWNER, OWNER, expected_issue_number=89)


def test_stale_approval_is_refused():
    item = issue()
    item["body"] += " post-approval change"
    history = comments()
    with pytest.raises(ValueError, match="stale"):
        implementation.authorize(item, history, history[-1], OWNER, OWNER, expected_issue_number=89)


@pytest.mark.parametrize("actor", ["external", "github-actions[bot]", ""])
def test_only_owner_can_implement(actor):
    history = comments()
    with pytest.raises(ValueError, match="repository owner"):
        implementation.authorize(
            issue(), history, history[-1], actor, OWNER, expected_issue_number=89
        )


def test_bogus_approval_receipt_is_refused():
    history = comments()
    history[2]["body"] = "approval forged"
    with pytest.raises(ValueError, match="not confirmed"):
        implementation.authorize(
            issue(), history, history[-1], OWNER, OWNER, expected_issue_number=89
        )


def test_safe_files_require_generator_ui_config_and_tests():
    paths = [
        "config.json",
        "ets_to_openhab.py",
        "knxproject_to_openhab.py",
        "web_ui/templates/index.html",
        "web_ui/static/app.js",
        "web_ui/static/i18n.js",
        "tests/test_rollershutter_homekit_extents.py",
    ]
    assert implementation.safe_paths(paths) == sorted(paths)


@pytest.mark.parametrize(
    "extra",
    [
        ".github/workflows/ci.yml",
        "scripts/issue89_impl.py",
        "../config.json",
        "/tmp/payload.py",
        "web_ui/static/other.js",
        "requirements.txt",
        "tests/test_bypass.py",
    ],
)
def test_unlisted_files_cannot_be_published(extra):
    good = list(implementation.REQUIRED_FILES) + [
        "tests/test_rollershutter_homekit_extents.py",
        extra,
    ]
    with pytest.raises(ValueError, match="allowlist"):
        implementation.safe_paths(good)


def test_missing_regression_test_is_refused():
    with pytest.raises(ValueError, match="regression"):
        implementation.safe_paths(list(implementation.REQUIRED_FILES))


def test_missing_generator_or_ui_change_is_refused():
    with pytest.raises(ValueError, match="incomplete"):
        implementation.safe_paths(["config.json", "tests/test_rollershutter_homekit_extents.py"])


def test_duplicates_and_empty_artifact_rejected():
    with pytest.raises(ValueError, match="duplicate"):
        implementation.safe_paths(["config.json", "config.json"])
    with pytest.raises(ValueError, match="No changes"):
        implementation.safe_paths([])


def test_multifile_artifact_is_checked_by_digest():
    paths = sorted(implementation.REQUIRED_FILES | {"tests/test_homekit_config_override.py"})
    files = []
    for path in paths:
        data = b"test\n"
        import base64

        files.append(
            {
                "path": path,
                "content_b64": base64.b64encode(data).decode("ascii"),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        )
    verified = implementation.inspect_artifact({"files": files})
    assert {part["path"] for part in verified} == set(paths)
    files[0]["sha256"] = "0" * 64
    with pytest.raises(ValueError, match="digest"):
        implementation.inspect_artifact({"files": files})


def test_wrong_event_or_issue_cannot_trigger(tmp_path, monkeypatch):
    item = issue()
    events = {
        "action": "created",
        "issue": {"number": 96},
        "comment": {"id": 400, "body": "/ai implement v2"},
    }
    event_path = tmp_path / "event.json"
    event_path.write_text(json.dumps(events), encoding="utf-8")
    (tmp_path / "issue-current.json").write_text(json.dumps(item), encoding="utf-8")
    (tmp_path / "issue-comments.json").write_text(json.dumps(comments()), encoding="utf-8")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event_path))
    monkeypatch.setenv("GITHUB_ACTOR", OWNER)
    monkeypatch.setenv("GITHUB_REPOSITORY_OWNER", OWNER)
    with pytest.raises(ValueError, match="Unexpected webhook"):
        implementation.resolve_event(tmp_path)


def test_agent_permissions_do_not_include_bash_or_repository_workflows():
    agent = (ROOT / ".opencode/agents/issue89-implementer.md").read_text(encoding="utf-8")
    assert "action: bash" not in agent
    assert "action: skill" in agent
    assert ".github/workflows/" not in [
        line.strip().removeprefix('resource: "').removesuffix('"')
        for line in agent.splitlines()
        if line.strip().startswith("resource:")
    ]


def test_workflow_keeps_implementation_and_publishing_separate():
    workflow = (ROOT / ".github/workflows/opencode-issue89-implement.yml").read_text(
        encoding="utf-8"
    )
    assert "github.event.issue.number == 89" in workflow
    assert "  implement:" in workflow
    assert "  publish:" in workflow
    assert "needs: implement" in workflow
    assert "python ../trusted/scripts/issue89_impl.py recheck" in workflow
    assert "draft: true" in workflow
    assert "createWorkflowDispatch" in workflow
    assert "auto_merge" not in workflow
