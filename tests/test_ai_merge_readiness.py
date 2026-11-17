"""Readiness checks distinguish software evidence from human acceptance."""

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
SPEC = importlib.util.spec_from_file_location(
    "ai_merge_readiness", ROOT / "scripts" / "ai_merge_readiness.py"
)
assert SPEC and SPEC.loader
readiness = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(readiness)

OWNER = "diddip21"
HEAD = "a" * 40


def snapshot():
    issue = {
        "number": 89,
        "state": "open",
        "title": "HomeKit blind settings",
        "body": "Approved plan v2",
        "labels": [{"name": "ai:approved"}, {"name": "ai:plan"}],
    }
    digest = hashlib.sha256(
        json.dumps(
            [issue["title"], issue["body"]],
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    comments = [
        {
            "id": 10,
            "user": {"login": "github-actions[bot]"},
            "body": '<!-- knx-issue-bot-state {"kind": "plan", '
            f'"version": 2, "issue_digest": "{digest}"}} -->\nPlan v2',
        },
        {"id": 20, "user": {"login": OWNER}, "body": "/ai approve v2"},
        {
            "id": 30,
            "user": {"login": "github-actions[bot]"},
            "body": "✅ **Plan v2 freigegeben.**",
        },
        {"id": 40, "user": {"login": OWNER}, "body": "/ai implement v2"},
    ]
    checks = [
        {
            "id": n,
            "name": name,
            "head_sha": HEAD,
            "started_at": "2026-11-17T12:00:00Z",
            "status": "completed",
            "conclusion": "success",
        }
        for n, name in enumerate(readiness.REQUIRED_CI, 1)
    ]
    return {
        "owner": OWNER,
        "repository": f"{OWNER}/knx_to_openhab",
        "pr": {
            "number": 108,
            "head_ref": "ai/issue-89-plan-v2-run-43893665720",
            "head_repo": f"{OWNER}/knx_to_openhab",
            "head_sha": HEAD,
            "base_ref": "dev",
            "state": "open",
            "draft": False,
            "mergeable": True,
            "author": "github-actions[bot]",
            "body": "<!-- ai-implementation-command: 40 -->",
        },
        "issue": issue,
        "issue_comments": comments,
        "checks": checks,
        "reviews": [
            {
                "user": {"login": "independent-reviewer"},
                "state": "APPROVED",
                "commit_id": HEAD,
                "submitted_at": "2026-11-17T13:00:00Z",
            }
        ],
        "unresolved_threads": 0,
        "files": [{"filename": "docs/screenshots/homekit-settings.png", "status": "added"}],
        "pr_comments": [
            {
                "user": {"login": OWNER},
                "body": (
                    f"/ai hardware-accepted {HEAD}\n"
                    "Datum: 2026-11-17\n"
                    "Aktor: Testgerät ohne private Adresse\n"
                    "Beobachtung: 0/100 % und Lamellen-Endlage geprüft\n"
                    "Rollback: vorherige Datei gesichert und Rückweg getestet"
                ),
            }
        ],
    }


def statuses(data):
    return {result["name"]: result["status"] for result in readiness.evaluate(data)}


def test_fully_evidenced_approved_dev_pr_can_pass():
    result = readiness.evaluate(snapshot())
    assert result
    assert all(item["status"] == "PASS" for item in result)


def test_draft_or_main_target_is_not_approved():
    data = snapshot()
    data["pr"]["draft"] = True
    assert statuses(data)["Bereit für Review"] == "OPEN"
    data["pr"]["base_ref"] = "main"
    assert statuses(data)["Branch und Ziel"] == "FAIL"


def test_stale_check_results_cannot_pass():
    data = snapshot()
    data["pr"]["head_sha"] = "b" * 40
    assert statuses(data)["CI am aktuellen Commit"] == "OPEN"


def test_failed_or_skipped_ci_remains_open():
    data = snapshot()
    data["checks"][0]["conclusion"] = "failure"
    assert statuses(data)["CI am aktuellen Commit"] == "OPEN"
    data["checks"][0]["conclusion"] = "skipped"
    assert statuses(data)["CI am aktuellen Commit"] == "OPEN"


def test_newer_failed_check_beats_old_success():
    data = snapshot()
    data["checks"].append(
        {
            "id": 100,
            "name": readiness.REQUIRED_CI[0],
            "head_sha": HEAD,
            "started_at": "2026-11-17T15:00:00Z",
            "status": "completed",
            "conclusion": "failure",
        }
    )
    assert statuses(data)["CI am aktuellen Commit"] == "OPEN"


def test_changed_issue_or_revoked_approval_is_not_approved():
    data = snapshot()
    data["issue"]["body"] += " new requirement"
    assert statuses(data)["Plan und Owner-Freigabe"] == "OPEN"
    data = snapshot()
    data["issue"]["labels"] = []
    assert statuses(data)["Plan und Owner-Freigabe"] == "OPEN"


def test_missing_implementation_command_blocks_plan_gate():
    data = snapshot()
    data["pr"]["body"] = "No trusted command marker"
    assert statuses(data)["Plan und Owner-Freigabe"] == "OPEN"


def test_codex_comment_is_not_an_approval():
    data = snapshot()
    data["reviews"] = [
        {
            "user": {"login": "chatgpt-codex-connector[bot]"},
            "state": "COMMENTED",
            "commit_id": HEAD,
            "submitted_at": "2026-11-17T15:00:00Z",
        }
    ]
    assert statuses(data)["Unabhängiges Code-Review"] == "OPEN"


def test_old_approval_or_self_approval_is_not_independent():
    data = snapshot()
    data["reviews"][0]["commit_id"] = "b" * 40
    assert statuses(data)["Unabhängiges Code-Review"] == "OPEN"
    data = snapshot()
    data["reviews"][0]["user"]["login"] = OWNER
    assert statuses(data)["Unabhängiges Code-Review"] == "OPEN"


def test_unresolved_threads_cannot_pass():
    data = snapshot()
    data["unresolved_threads"] = 1
    assert statuses(data)["Review-Diskussionen"] == "OPEN"


def test_screenshots_and_hardware_are_explicit_gates():
    data = snapshot()
    data["files"] = []
    data["pr_comments"] = []
    result = statuses(data)
    assert result["UI-Belege"] == "OPEN"
    assert result["KNX-Hardwareabnahme (Owner-Erklärung)"] == "OPEN"


def test_hardware_acceptance_bound_to_head_and_owner():
    data = snapshot()
    data["pr_comments"][0]["body"] = data["pr_comments"][0]["body"].replace(
        HEAD, "b" * 40
    )
    assert statuses(data)["KNX-Hardwareabnahme (Owner-Erklärung)"] == "OPEN"
    data = snapshot()
    data["pr_comments"][0]["user"]["login"] = "attacker"
    assert statuses(data)["KNX-Hardwareabnahme (Owner-Erklärung)"] == "OPEN"


def test_snapshot_output_never_claims_automatic_merge(tmp_path, monkeypatch):
    data = snapshot()
    data["pr_comments"] = []
    snapshot_path = tmp_path / "snapshot.json"
    output_path = tmp_path / "audit.json"
    snapshot_path.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "ai_merge_readiness.py",
            "--snapshot",
            str(snapshot_path),
            "--report",
            str(output_path),
        ],
    )
    assert readiness.main() == 1
    assert json.loads(output_path.read_text(encoding="utf-8"))["ready"] is False


@pytest.mark.parametrize("bad", [{}, {"pr": {"head_ref": "bad", "draft": False}}])
def test_unknown_data_fails_closed(bad):
    result = readiness.evaluate(bad)
    assert any(item["status"] != "PASS" for item in result)
