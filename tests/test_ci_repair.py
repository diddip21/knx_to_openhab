"""Fail-closed tests for approved HomeKit CI repair workflows."""

import base64
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
SCRIPT = ROOT / "scripts" / "ci_repair.py"
SPEC = importlib.util.spec_from_file_location("ci_repair", SCRIPT)
assert SPEC and SPEC.loader
ci = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ci)

OWNER = "diddip21"
HEAD = "a" * 40
BRANCH = "ai/issue-89-plan-v2-run-43893665720"


def live_source():
    issue = {
        "number": 89,
        "title": "HomeKit blinds",
        "body": "Approved plan v2",
        "state": "open",
        "labels": [{"name": "ai:approved"}, {"name": "ai:plan"}],
    }
    marker = {
        "version": 2,
        "kind": "plan",
        "issue_digest": ci.hashlib.sha256(
            json.dumps(
                [issue["title"], issue["body"]],
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode()
        ).hexdigest(),
    }
    comments = [
        {
            "id": 10,
            "user": {"login": "github-actions[bot]"},
            "body": "<!-- knx-issue-bot-state " + json.dumps(marker) + " -->\nPlan",
        },
        {"id": 20, "user": {"login": OWNER}, "body": "/ai approve v2"},
        {
            "id": 30,
            "user": {"login": "github-actions[bot]"},
            "body": "\u2705 **Plan v2 freigegeben.**",
        },
        {"id": 40, "user": {"login": OWNER}, "body": "/ai implement v2"},
    ]
    pr = {
        "number": 108,
        "state": "open",
        "draft": True,
        "user": {"login": "github-actions[bot]"},
        "head": {
            "ref": BRANCH,
            "sha": HEAD,
            "repo": {"full_name": "diddip21/knx_to_openhab"},
        },
        "base": {"ref": "main"},
        "body": "Approval comment: 20; implementation command: 40",
    }
    return {
        "pr": pr,
        "issue": issue,
        "comments": comments,
        "commits": [{"commit": {"message": "feat(homekit): issue #89"}}],
    }


def make_event(tmp_path, monkeypatch, **run_overrides):
    run = {
        "name": "CI",
        "event": "workflow_dispatch",
        "conclusion": "failure",
        "head_branch": BRANCH,
        "head_sha": HEAD,
        "id": 123456,
        "repository": {"full_name": "diddip21/knx_to_openhab"},
    }
    run.update(run_overrides)
    path = tmp_path / "workflow_event.json"
    path.write_text(json.dumps({"action": "completed", "workflow_run": run}))
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(path))
    monkeypatch.setenv("GITHUB_REPOSITORY", "diddip21/knx_to_openhab")
    monkeypatch.setenv("GITHUB_REPOSITORY_OWNER", OWNER)


def test_owner_approved_issue89_pr_is_eligible(tmp_path, monkeypatch):
    make_event(tmp_path, monkeypatch)
    outcome = ci.check_authorization(live_source(), OWNER)
    assert outcome["attempt"] == 1
    assert outcome["pr_number"] == 108
    assert outcome["head_sha"] == HEAD


@pytest.mark.parametrize(
    ("override", "error"),
    [
        ({"conclusion": "success"}, "Not a failed"),
        ({"event": "pull_request"}, "Not a failed"),
        ({"head_branch": "random"}, "Not an approved"),
        ({"head_sha": "invalid"}, "Not an approved"),
        ({"repository": {"full_name": "attacker/repo"}}, "Not a failed"),
    ],
)
def test_unrelated_events_rejected(tmp_path, monkeypatch, override, error):
    make_event(tmp_path, monkeypatch, **override)
    with pytest.raises(ValueError, match=error):
        ci.check_authorization(live_source(), OWNER)


def test_stale_commit_rejected(tmp_path, monkeypatch):
    make_event(tmp_path, monkeypatch)
    source = live_source()
    source["pr"]["head"]["sha"] = "b" * 40
    with pytest.raises(ValueError, match="Live PR"):
        ci.check_authorization(source, OWNER)


def test_nonbot_or_non_draft_rejected(tmp_path, monkeypatch):
    make_event(tmp_path, monkeypatch)
    for key, value in (
        ("draft", False),
        ("user", {"login": "someone-else"}),
        ("state", "closed"),
    ):
        source = live_source()
        source["pr"][key] = value
        with pytest.raises(ValueError, match="Live PR"):
            ci.check_authorization(source, OWNER)


def test_repair_attempts_are_bounded(tmp_path, monkeypatch):
    make_event(tmp_path, monkeypatch)
    source = live_source()
    source["commits"].append({"commit": {"message": "fix(ai-ci): issue89 attempt 1"}})
    assert ci.check_authorization(source, OWNER)["attempt"] == 2
    source["commits"].append({"commit": {"message": "fix(ai-ci): issue89 attempt 2"}})
    with pytest.raises(ValueError, match="Maximum of two"):
        ci.check_authorization(source, OWNER)


def test_bad_or_duplicate_round_markers_rejected(tmp_path, monkeypatch):
    make_event(tmp_path, monkeypatch)
    source = live_source()
    source["commits"].append({"commit": {"message": "fix(ai-ci): issue89 attempt 2"}})
    with pytest.raises(ValueError, match="Out-of-order"):
        ci.check_authorization(source, OWNER)
    source["commits"][-1]["commit"]["message"] = "fix(ai-ci): issue89 attempt 9"
    with pytest.raises(ValueError, match="Unrecognized"):
        ci.check_authorization(source, OWNER)


def test_revoked_approval_is_rejected(tmp_path, monkeypatch):
    make_event(tmp_path, monkeypatch)
    source = live_source()
    source["issue"]["labels"] = [{"name": "ai:waiting"}]
    with pytest.raises(ValueError, match="not approved"):
        ci.check_authorization(source, OWNER)


def test_changed_issue_fails_closed(tmp_path, monkeypatch):
    make_event(tmp_path, monkeypatch)
    source = live_source()
    source["issue"]["body"] += "\nAdditional requirements"
    with pytest.raises(ValueError, match="stale"):
        ci.check_authorization(source, OWNER)


def test_hidden_implementation_reference_survives_description_rewrites(tmp_path, monkeypatch):
    make_event(tmp_path, monkeypatch)
    source = live_source()
    source["pr"]["body"] = (
        "Deutsche PR-Beschreibung mit Zusammenfassung.\n" "<!-- ai-implementation-command: 40 -->"
    )
    assert ci.check_authorization(source, OWNER)["command_comment_id"] == 40


def test_untrusted_pr_body_cannot_invent_command(tmp_path, monkeypatch):
    make_event(tmp_path, monkeypatch)
    source = live_source()
    source["pr"]["body"] = "No implementation command"
    with pytest.raises(ValueError, match="no trusted implementation"):
        ci.check_authorization(source, OWNER)


def test_candidate_change_is_limited_to_existing_allowlisted_files(monkeypatch):
    def fake_git(*args):
        if args[0:2] == ("diff", "--name-only"):
            if args[2] == "--diff-filter=ACM":
                return "ets_to_openhab.py\ntests/test_rollershutter_homekit_extents.py"
            return ""
        if args[0] == "ls-files":
            return ""
        if args[0:2] == ("diff", "--numstat"):
            return "3\t2\tets_to_openhab.py"
        raise AssertionError(args)

    monkeypatch.setattr(ci, "git", fake_git)
    monkeypatch.setattr(ci.subprocess, "run", lambda *a, **k: type("R", (), {"returncode": 0})())
    assert ci.changed_files() == [
        "ets_to_openhab.py",
        "tests/test_rollershutter_homekit_extents.py",
    ]


def test_repair_artifact_checks_digest_paths_and_size():
    data = b"print('ok')\n"
    one = {
        "path": "ets_to_openhab.py",
        "content_b64": base64.b64encode(data).decode("ascii"),
        "sha256": hashlib.sha256(data).hexdigest(),
    }
    ci.verify_artifact({"files": [one]})
    with pytest.raises(ValueError, match="Altered"):
        ci.verify_artifact({"files": [{**one, "sha256": "0" * 64}]})
    with pytest.raises(ValueError, match="allowlist"):
        ci.verify_artifact({"files": [{**one, "path": ".github/workflows/ci.yml"}]})
    with pytest.raises(ValueError, match="duplicate"):
        ci.verify_artifact({"files": [one, one]})


def test_diagnostics_are_explicitly_untrusted_and_bounded(tmp_path):
    (tmp_path / "ci-failed.log").write_text("evil-instructions " * 10_000)
    prompt = ci.prompt_for_failure({"pr_number": 108, "attempt": 1}, tmp_path)
    assert "UNTRUSTED DATA" in prompt
    assert "weaken failing tests" in prompt
    assert len(prompt) < 52_000


def test_workflow_separates_unprivileged_agent_from_publisher():
    workflow = (ROOT / ".github/workflows/opencode-ci-self-repair.yml").read_text()
    assert "  repair:" in workflow
    assert "  publish:" in workflow
    assert "needs: repair" in workflow
    assert "types: [completed]" in workflow
    assert "workflow_dispatch" in workflow
    assert "draft" in workflow
    assert "force:false" in workflow
    assert "createWorkflowDispatch" in workflow
    assert "autoMerge" not in workflow


def test_repair_agent_denies_shell_and_new_files():
    agent = (ROOT / ".opencode/agents/issue89-ci-repair.md").read_text()
    assert "action: bash" not in agent
    assert "action: write" not in agent
    assert "action: edit" in agent
