"""Offline E2E: real Git and pytest, deterministic edits instead of a live model/API."""

import json
import os
import shutil
import subprocess
import sys

import pytest
from automation import artifacts

from .helpers import OWNER, ROOT, context, git, init_repo, module, repair_source, set_event

ci = module("ci_repair")


def run_core(root):
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    # Avoid timestamp-dependent stale .pyc reuse between the deliberate failure and fix.
    for cache in root.rglob("__pycache__"):
        shutil.rmtree(cache)
    return subprocess.run(
        [sys.executable, "-B", "-m", "pytest", "-q", "tests/test_feature.py"],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


@pytest.mark.parametrize("number,version", [(89, 3), (1234, 5)])
def test_approved_task_failing_ci_repair_and_green_ci(tmp_path, monkeypatch, number, version):
    root = init_repo(tmp_path / "candidate")
    initial = context(root, number, version)
    # This deliberate error exists only in a temporary synthetic repository.
    (root / "feature.py").write_text("value = 2\n")
    (root / "tests/test_feature.py").write_text(
        "from feature import value\n\ndef test_value():\n    assert value == 1\n"
    )
    candidate = artifacts.collect(initial, root, repair=False)
    verified = artifacts.recheck(candidate, initial, root, repair=False)
    assert len(verified["files"]) == 2
    git(root, "add", "feature.py", "tests/test_feature.py")
    git(root, "commit", "-qm", f"feat(ai): issue {number} plan v{version}")
    failed = run_core(root)
    assert failed.returncode != 0 and "1 failed" in failed.stdout
    source = repair_source(root, number, version)
    set_event(tmp_path, monkeypatch, source)
    authorized_repair = ci.check_authorization(source, OWNER)
    assert authorized_repair["attempt"] == 1
    (root / "feature.py").write_text("value = 1\n")
    repair = artifacts.collect(authorized_repair, root, repair=True)
    checked = artifacts.recheck(repair, authorized_repair, root, repair=True)
    assert [f["path"] for f in checked["files"]] == ["feature.py"]
    git(root, "add", "feature.py")
    git(root, "commit", "-qm", f"fix(ai-ci): issue {number} plan v{version} attempt 1")
    green = run_core(root)
    assert green.returncode == 0 and "1 passed" in green.stdout
    # The original failed run must not authorize another write after HEAD advances.
    source["pr"]["head"]["sha"] = git(root, "rev-parse", "HEAD")
    with pytest.raises(ValueError, match="Live PR"):
        ci.check_authorization(source, OWNER)


def test_real_cli_uses_trusted_imports_and_restores_generated_agent(tmp_path, monkeypatch):
    trusted = init_repo(tmp_path / "trusted")
    (trusted / "scripts").mkdir()
    shutil.copy2(ROOT / "scripts/issue_implement.py", trusted / "scripts/issue_implement.py")
    shutil.copytree(
        ROOT / "scripts/automation",
        trusted / "scripts/automation",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    shutil.copy2(ROOT / ".opencode/agents/ai-task.md", trusted / ".opencode/agents/ai-task.md")
    git(trusted, "add", ".")
    git(trusted, "commit", "-qm", "trusted controller fixture")
    root = tmp_path / "candidate"
    subprocess.run(
        ["git", "clone", "--no-hardlinks", str(trusted), str(root)], check=True, capture_output=True
    )
    from .helpers import fixture

    issue, history = fixture(1234, 5)
    temporary = tmp_path / "runtime"
    temporary.mkdir()
    artifacts.write_json(temporary / "issue-current.json", issue)
    artifacts.write_json(temporary / "issue-comments.json", history)
    artifacts.write_json(
        temporary / "event.json", {"action": "created", "issue": issue, "comment": history[-1]}
    )
    env = os.environ | {
        "RUNNER_TEMP": str(temporary),
        "GITHUB_EVENT_NAME": "issue_comment",
        "GITHUB_EVENT_PATH": str(temporary / "event.json"),
        "GITHUB_ACTOR": OWNER,
        "GITHUB_REPOSITORY_OWNER": OWNER,
        "GITHUB_REPOSITORY": f"{OWNER}/sample",
        "GITHUB_RUN_ID": "1000",
    }
    # A candidate-local stdlib shadow must never execute in a trusted controller.
    marker = tmp_path / "untrusted-import-ran"
    (root / "json.py").write_text(f"open({str(marker)!r}, 'w').write('unsafe')\n")

    def run(action):
        result = subprocess.run(
            [sys.executable, "-I", str(trusted / "scripts/issue_implement.py"), action],
            cwd=root,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr

    run("prepare")
    assert not marker.exists()
    (root / "json.py").unlink()
    original = (root / ".opencode/agents/ai-task.md").read_bytes()
    run("agent")
    assert (root / ".opencode/agents/ai-task.md").read_bytes() != original
    git(root, "restore", "--source=HEAD", "--worktree", "--", ".opencode/agents/ai-task.md")
    assert (root / ".opencode/agents/ai-task.md").read_bytes() == original
    (root / "feature.py").write_text("value = 1\n")
    (root / "tests/test_feature.py").write_text("def test_example():\n    assert 1 == 1\n")
    run("collect")
    run("recheck")
    verified = json.loads((temporary / "task-verified.json").read_text())
    assert verified["issue_number"] == 1234
    assert {f["path"] for f in verified["files"]} == {"feature.py", "tests/test_feature.py"}
