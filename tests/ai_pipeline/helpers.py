"""Synthetic multi-issue fixtures, not production task policies."""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from automation.approval import digest  # noqa: E402
from automation.scope import authorize_task, task_reference  # noqa: E402

OWNER = "test-owner"
REPOSITORY = f"{OWNER}/sample"


def module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    assert spec and spec.loader
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def fixture(number=89, version=3, scope=None):
    issue = {
        "number": number,
        "state": "open",
        "title": "Synthetic feature",
        "body": "A controller test, not a real deployment.",
        "labels": [{"name": "ai:plan"}, {"name": "ai:approved"}],
    }
    scope = scope or {
        "files": ["feature.py", "tests/test_feature.py", "docs/feature.md"],
        "create": [],
        "required": ["tests/test_feature.py"],
    }
    marker = {"kind": "plan", "version": version, "issue_digest": digest(issue)}
    comments = [
        {
            "id": 10,
            "user": {"login": "github-actions[bot]"},
            "body": "<!-- knx-issue-bot-state " + json.dumps(marker) + " -->\nSynthetic plan",
        },
        {"id": 20, "user": {"login": OWNER}, "body": f"/ai approve v{version}"},
        {
            "id": 30,
            "user": {"login": "github-actions[bot]"},
            "body": f"\u2705 **Plan v{version} freigegeben.**",
        },
        {
            "id": 40,
            "user": {"login": OWNER},
            "body": f"/ai implement v{version}\n```json\n" + json.dumps(scope) + "\n```",
        },
    ]
    for i, comment in enumerate(comments):
        comment["created_at"] = comment["updated_at"] = f"2026-01-01T00:00:0{i}Z"
    return issue, comments


def context(root, number=89, version=3, scope=None):
    issue, history = fixture(number, version, scope)
    result = authorize_task(issue, history, history[-1], OWNER, OWNER, expected_issue_number=number)
    result.update(
        {
            "base_commit_sha": git(root, "rev-parse", "HEAD"),
            "trusted_sha": "f" * 40,
            "repository": REPOSITORY,
            "run_id": 1000,
            "mode": "implement",
        }
    )
    return result


def git(root, *args):
    return subprocess.run(
        ["git", "-C", str(root), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def init_repo(root):
    root.mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "docs").mkdir()
    (root / ".opencode/agents").mkdir(parents=True)
    (root / ".opencode/agents/ai-task.md").write_text("---\npermissions: []\n---\nTest\n")
    (root / ".gitignore").write_text("__pycache__/\n.pytest_cache/\n")
    (root / "feature.py").write_text("value = 0\n")
    (root / "tests/test_feature.py").write_text(
        "from feature import value\n\ndef test_value():\n    assert value == 0\n"
    )
    (root / "docs/feature.md").write_text("# Synthetic feature\n")
    git(root, "init", "-q")
    git(root, "config", "user.name", "Test")
    git(root, "config", "user.email", "test@example.invalid")
    git(root, "add", ".")
    git(root, "commit", "-qm", "test base")
    return root


def repair_source(root, number=89, version=3):
    issue, comments = fixture(number, version)
    approved = context(root, number, version)
    branch = f"ai/issue-{number}-plan-v{version}-run-1000"
    run = {
        "id": 6000,
        "run_attempt": 1,
        "name": "CI",
        "path": ".github/workflows/ci.yml",
        "event": "workflow_dispatch",
        "status": "completed",
        "conclusion": "failure",
        "head_sha": approved["base_commit_sha"],
        "head_branch": branch,
        "head_repository": {"full_name": REPOSITORY},
    }
    pr = {
        "number": 50,
        "state": "open",
        "draft": True,
        "user": {"login": "github-actions[bot]"},
        "head": {"ref": branch, "sha": run["head_sha"], "repo": {"full_name": REPOSITORY}},
        "base": {"ref": "dev"},
        "body": "<!-- ai-implementation-command: 40 -->\n"
        + "<!-- ai-task: "
        + json.dumps(task_reference(approved))
        + " -->",
    }
    return {
        "issue": issue,
        "comments": comments,
        "run": run,
        "pr": pr,
        "commits": [{"commit": {"message": f"feat(ai): issue {number} plan v{version}"}}],
    }


def set_event(tmp_path, monkeypatch, source):
    event = {"action": "completed", "workflow_run": source["run"].copy()}
    file = tmp_path / "event.json"
    file.write_text(json.dumps(event), encoding="utf-8")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(file))
    monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_run")
    monkeypatch.setenv("GITHUB_REPOSITORY", REPOSITORY)
    monkeypatch.setenv("GITHUB_REPOSITORY_OWNER", OWNER)
