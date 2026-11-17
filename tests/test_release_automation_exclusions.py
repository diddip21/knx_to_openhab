"""Release archives exclude CI/AI tooling without removing runtime helpers."""

import hashlib
import importlib.util
import subprocess
import tarfile
from pathlib import Path, PurePosixPath

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("release_builder", ROOT / "scripts/build_release.py")
assert SPEC and SPEC.loader
release = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release)

AUTOMATION_FILES = [
    ".github/workflows/ci.yml",
    ".opencode/agents/ai-task.md",
    ".opencode/agents/future-agent.md",
    "opencode.jsonc",
    "opencode.json",
    "scripts/ai_merge_readiness.py",
    "scripts/ci_repair.py",
    "scripts/issue89_impl.py",
    "scripts/issue_bot.py",
    "scripts/issue_impl.py",
    "scripts/issue_implement.py",
    "scripts/opencode_model_router.py",
    "scripts/automation/__init__.py",
    "scripts/automation/approval.py",
    "scripts/automation/github.cjs",
    "scripts/automation/future_controller.py",
]
APPLICATION_FILES = [
    "VERSION",
    "config.json",
    "ets_to_openhab.py",
    "knxproject_to_openhab.py",
    "web_ui/backend/app.py",
    "installer/install.sh",
    "scripts/build_release.py",
    "scripts/dev-setup.sh",
    "scripts/dev-setup.ps1",
    "scripts/dev-run.sh",
    "scripts/dev-run.ps1",
    "scripts/verify-setup.sh",
    "scripts/verify-setup.ps1",
    "scripts/regenerate_golden.py",
]


@pytest.mark.parametrize("path", AUTOMATION_FILES)
def test_automation_paths_are_excluded(path):
    assert release.is_excluded_release_path(PurePosixPath(path))


@pytest.mark.parametrize("path", APPLICATION_FILES)
def test_application_and_development_helpers_are_preserved(path):
    assert not release.is_excluded_release_path(PurePosixPath(path))


@pytest.mark.parametrize("from_git_index", [False, True])
def test_actual_archive_contents_checksum_and_reproducibility(tmp_path, from_git_index):
    repo = tmp_path / "repo"
    repo.mkdir()
    for name in APPLICATION_FILES + AUTOMATION_FILES:
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("1.2.3\n" if name == "VERSION" else f"Fixture for {name}\n")
    kwargs = {}
    if from_git_index:
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    else:
        kwargs["tracked_files"] = [
            (PurePosixPath(name), 0o100644) for name in APPLICATION_FILES + AUTOMATION_FILES
        ]
    archive, checksum = release.build_release(repo, "1.2.3", tmp_path / "dist", **kwargs)
    first_bytes = archive.read_bytes()
    with tarfile.open(archive, "r:gz") as bundle:
        actual = {member.name for member in bundle.getmembers() if member.isfile()}
    assert actual == {f"knx_to_openhab-1.2.3/{name}" for name in APPLICATION_FILES}
    assert checksum.read_text() == f"{hashlib.sha256(first_bytes).hexdigest()}  {archive.name}\n"
    again, _ = release.build_release(repo, "1.2.3", tmp_path / "dist-again", **kwargs)
    assert again.read_bytes() == first_bytes
