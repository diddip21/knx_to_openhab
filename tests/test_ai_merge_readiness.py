"""Readiness is based on the change and actual evidence, not a special issue number."""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
SPEC = importlib.util.spec_from_file_location("readiness", ROOT / "scripts/ai_merge_readiness.py")
assert SPEC and SPEC.loader
readiness = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(readiness)

from automation.scope import authorize_task, task_reference  # noqa: E402


def snapshot(number=89, version=3):
    from tests.ai_pipeline.helpers import OWNER, fixture

    issue, comments = fixture(number, version)
    approved = authorize_task(
        issue, comments, comments[-1], OWNER, OWNER, expected_issue_number=number
    )
    approved["base_commit_sha"] = "b" * 40
    sha = "a" * 40
    return {
        "owner": OWNER,
        "repository": f"{OWNER}/sample",
        "pr": {
            "number": 50,
            "head_ref": f"ai/issue-{number}-plan-v{version}-run-1000",
            "head_sha": sha,
            "head_repo": f"{OWNER}/sample",
            "base_ref": "dev",
            "state": "open",
            "draft": False,
            "mergeable": True,
            "author": "github-actions[bot]",
            "body": "<!-- ai-implementation-command: 40 -->\n"
            + "<!-- ai-task: "
            + json.dumps(task_reference(approved))
            + " -->",
        },
        "issue": issue,
        "issue_comments": comments,
        "checks": [
            {
                "id": n,
                "name": name,
                "head_sha": sha,
                "status": "completed",
                "conclusion": "success",
                "app_slug": "github-actions",
                "started_at": "2026-01-01T12:00:00Z",
            }
            for n, name in enumerate(readiness.REQUIRED_CI, 1)
        ],
        "reviews": [
            {
                "user": {"login": OWNER, "type": "User"},
                "state": "APPROVED",
                "commit_id": sha,
                "submitted_at": "2026-01-01T13:00:00Z",
            }
        ],
        "unresolved_threads": 0,
        "files": [{"filename": "feature.py", "status": "modified"}],
    }


def statuses(data):
    return {g["name"]: g["status"] for g in readiness.evaluate(data)}


@pytest.mark.parametrize("number,version", [(89, 3), (1234, 5)])
def test_fully_evidenced_different_tasks_pass_without_hardware(number, version):
    result = statuses(snapshot(number, version))
    assert result and all(state == "PASS" for state in result.values())
    assert all("Hardware" not in name for name in result)


@pytest.mark.parametrize(
    "change",
    [
        "draft",
        "main",
        "stale_checks",
        "failed",
        "skipped",
        "fake_app",
        "no_approval",
        "bot_review",
        "old_review",
        "objection",
        "threads",
        "unknown_threads",
        "no_scope",
        "missing_diff",
    ],
)
def test_missing_or_stale_evidence_never_passes(change):
    data = snapshot()
    if change == "draft":
        data["pr"]["draft"] = True
    elif change == "main":
        data["pr"]["base_ref"] = "main"
    elif change == "stale_checks":
        data["checks"][0]["head_sha"] = "c" * 40
    elif change in {"failed", "skipped"}:
        data["checks"][0]["conclusion"] = "failure" if change == "failed" else "skipped"
    elif change == "fake_app":
        data["checks"][0]["app_slug"] = "another-app"
    elif change == "no_approval":
        data["reviews"] = []
    elif change == "bot_review":
        data["reviews"][0]["user"]["type"] = "Bot"
    elif change == "old_review":
        data["reviews"][0]["commit_id"] = "c" * 40
    elif change == "objection":
        data["reviews"].append(
            {
                "user": {"login": "reviewer-2", "type": "User"},
                "state": "CHANGES_REQUESTED",
                "commit_id": "a" * 40,
                "submitted_at": "2026-01-01T14:00:00Z",
            }
        )
    elif change == "threads":
        data["unresolved_threads"] = 1
    elif change == "unknown_threads":
        data["unresolved_threads"] = False
    elif change == "no_scope":
        data["issue_comments"][-1]["body"] = "/ai implement v3"
    else:
        data.pop("files")
    assert any(state != "PASS" for state in statuses(data).values())


@pytest.mark.parametrize("number", [89, 1234])
def test_ui_evidence_follows_file_changes_for_every_issue(number):
    data = snapshot(number)
    data["files"] = [{"filename": "web_ui/static/app.js", "status": "modified"}]
    assert statuses(data)["UI-Belege"] == "OPEN"
    data["files"].append({"filename": "docs/screenshots/settings.png", "status": "added"})
    assert statuses(data)["UI-Belege"] == "PASS"
    data["files"][-1]["status"] = "removed"
    assert statuses(data)["UI-Belege"] == "OPEN"


def test_later_failed_check_overrides_success_even_with_equal_timestamps():
    data = snapshot()
    data["checks"].append({**data["checks"][0], "id": 100, "conclusion": "failure"})
    assert statuses(data)["CI am aktuellen Commit"] == "OPEN"


def test_plain_review_comment_does_not_revoke_real_approval():
    data = snapshot()
    data["reviews"].append(
        {**data["reviews"][0], "state": "COMMENTED", "submitted_at": "2026-01-01T14:00:00Z"}
    )
    assert statuses(data)["Unabhaengiges Code-Review"] == "PASS"


def test_unknown_snapshot_fails_closed():
    assert any(state != "PASS" for state in statuses({}).values())


def test_report_has_current_sha_and_nonzero_exit_for_open_gate(tmp_path, monkeypatch):
    data = snapshot()
    data["reviews"] = []
    source, report, summary = (
        tmp_path / name for name in ("snapshot.json", "report.json", "summary.md")
    )
    source.write_text(json.dumps(data))
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    monkeypatch.setattr(
        sys, "argv", ["readiness", "--snapshot", str(source), "--report", str(report)]
    )
    assert readiness.main() == 1
    result = json.loads(report.read_text())
    assert result["ready"] is False
    assert result["sha"] == data["pr"]["head_sha"]
    assert "Keine automatische Merge-Freigabe" in summary.read_text()
