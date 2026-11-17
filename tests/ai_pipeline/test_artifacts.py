"""Real Git diffs and independent publisher validation, including malicious artifacts."""

import base64
import copy
import hashlib
import json
import os
import subprocess

import pytest

from .helpers import ROOT, context, git, init_repo
from automation import artifacts


def change_code(root):
    (root / "feature.py").write_text("value = 1\n")
    (root / "tests/test_feature.py").write_text(
        "from feature import value\n\ndef test_value():\n    assert value == 1\n"
    )


@pytest.mark.parametrize("number,version", [(89, 3), (1234, 5)])
def test_same_collect_and_independent_recheck_for_different_tasks(tmp_path, number, version):
    root = init_repo(tmp_path / "candidate")
    approved = context(root, number, version)
    target = tmp_path / "target"
    subprocess.run(["git", "clone", "--no-hardlinks", str(root), str(target)], check=True,
                   capture_output=True)
    change_code(root)
    candidate = artifacts.collect(approved, root, repair=False)
    checked = artifacts.recheck(candidate, approved, target, repair=False)
    assert checked["scope_sha256"] == approved["scope_sha256"]
    assert {f["path"] for f in checked["files"]} == {"feature.py", "tests/test_feature.py"}
    assert all(f["mode"] == "100644" for f in checked["files"])
    assert git(target, "status", "--porcelain") == ""


@pytest.mark.parametrize("field", ["digest", "scope_sha256", "command_sha256", "plan_sha256",
                                   "base_commit_sha", "trusted_sha", "run_id", "issue_number",
                                   "version", "scope", "repository"])
def test_artifact_cannot_authorize_itself(tmp_path, field):
    root = init_repo(tmp_path / "candidate")
    approved = context(root)
    change_code(root)
    candidate = artifacts.collect(approved, root, repair=False)
    candidate[field] = "forged"
    with pytest.raises(ValueError, match="metadata"):
        artifacts.recheck(candidate, approved, root, repair=False)


@pytest.mark.parametrize("mutation", ["digest", "path", "extra", "duplicate", "empty", "binary",
                                      "whitespace", "oversize", "no_test", "no_op"])
def test_candidate_file_tampering_rejected(tmp_path, mutation):
    root = init_repo(tmp_path / "candidate")
    approved = context(root)
    change_code(root)
    candidate = artifacts.collect(approved, root, repair=False)
    records = candidate["files"]
    if mutation == "digest":
        records[0]["sha256"] = "0" * 64
    elif mutation == "path":
        records[0]["path"] = ".github/workflows/ci.yml"
    elif mutation == "extra":
        records[0]["mode"] = "120000"
    elif mutation == "duplicate":
        records.append(copy.deepcopy(records[0]))
    elif mutation == "empty":
        records.clear()
    elif mutation == "no_test":
        records[:] = [r for r in records if not r["path"].startswith("tests/")]
    else:
        payload = {"binary": b"bad\x00file", "whitespace": b"value = 1  \n",
                   "oversize": b"a" * 300001, "no_op": b"value = 0\n"}[mutation]
        record = next(r for r in records if r["path"] == "feature.py")
        record["content_b64"] = base64.b64encode(payload).decode()
        record["sha256"] = hashlib.sha256(payload).hexdigest()
    with pytest.raises(ValueError):
        artifacts.recheck(candidate, approved, root, repair=False)


def test_new_files_need_explicit_create_permission(tmp_path):
    root = init_repo(tmp_path / "candidate")
    scope = {"files": ["feature.py", "tests/test_extra.py"], "create": ["tests/test_extra.py"]}
    approved = context(root, scope=scope)
    (root / "feature.py").write_text("value = 1\n")
    (root / "tests/test_extra.py").write_text("def test_extra():\n    assert True\n")
    artifact = artifacts.collect(approved, root, repair=False)
    assert len(artifact["files"]) == 2
    with pytest.raises(ValueError, match="new file during repair"):
        artifacts.validate_files(artifact["files"], approved, root, repair=True)
    forbidden = copy.deepcopy(approved)
    forbidden["scope"]["create"] = []
    with pytest.raises(ValueError, match="explicitly approved"):
        artifacts.validate_files(artifact["files"], forbidden, root, repair=False)


@pytest.mark.parametrize("attack", ["symlink", "parent_symlink", "hardlink", "delete", "rename"])
def test_filesystem_attacks_rejected(tmp_path, attack):
    root = init_repo(tmp_path / "candidate")
    approved = context(root)
    change_code(root)
    if attack == "symlink":
        (root / "feature.py").unlink()
        (root / "feature.py").symlink_to(root / "docs/feature.md")
    elif attack == "parent_symlink":
        (root / "docs").rename(root / "moved")
        (root / "docs").symlink_to(root / "moved", target_is_directory=True)
        with pytest.raises(ValueError, match="Symlink"):
            artifacts.file_bytes(root, "docs/feature.md")
        return
    elif attack == "hardlink":
        (root / "feature.py").unlink()
        os.link(root / "docs/feature.md", root / "feature.py")
    elif attack == "delete":
        (root / "docs/feature.md").unlink()
    else:
        git(root, "mv", "docs/feature.md", "docs/renamed.md")
    with pytest.raises(ValueError):
        artifacts.collect(approved, root, repair=False)


def test_executable_mode_is_preserved_by_publisher(tmp_path):
    root = init_repo(tmp_path / "candidate")
    (root / "feature.py").chmod(0o755)
    git(root, "add", "feature.py")
    git(root, "commit", "-qm", "executable fixture")
    approved = context(root)
    change_code(root)
    candidate = artifacts.collect(approved, root, repair=False)
    checked = artifacts.recheck(candidate, approved, root, repair=False)
    assert next(f["mode"] for f in checked["files"] if f["path"] == "feature.py") == "100755"


def test_agent_permissions_are_literal_and_missing_repair_files_are_not_granted(tmp_path):
    root = init_repo(tmp_path / "candidate")
    approved = context(root, scope={"files": ["feature.py", "tests/test_extra.py"],
                                    "create": ["tests/test_extra.py"]})
    template = ROOT / ".opencode/agents/ai-task.md"
    artifacts.write_agent(root, approved, template, repair=False)
    header = json.loads((root / ".opencode/agents/ai-task.md").read_text().split("---")[1])
    allowed = [r for r in header["permissions"] if r["effect"] == "allow" and r["action"] == "edit"]
    assert {r["resource"] for r in allowed} == {"feature.py", "tests/test_extra.py",
                                               str(root / "feature.py"), str(root / "tests/test_extra.py")}
    assert all("*" not in r["resource"] for r in allowed)
    assert not any(r["action"] in {"shell", "subagent", "execute", "external_directory"}
                   and r["effect"] == "allow" for r in header["permissions"])
    artifacts.write_agent(root, approved, template, repair=True)
    repair = json.loads((root / ".opencode/agents/ai-task.md").read_text().split("---")[1])
    assert not any("test_extra.py" in r["resource"] for r in repair["permissions"])


def test_diff_budget_is_checked_independently(tmp_path):
    root = init_repo(tmp_path / "candidate")
    approved = context(root)
    change_code(root)
    (root / "feature.py").write_text("# changed\n" * 2600)
    with pytest.raises(ValueError, match="diff is too large"):
        artifacts.collect(approved, root, repair=False)
