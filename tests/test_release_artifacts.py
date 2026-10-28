import hashlib
import json
import os
import subprocess
import tarfile
from pathlib import Path

import pytest

from scripts.build_release import ReleaseArtifactError, build_release, validate_semver, validate_tag


def _repository(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    files = {
        "VERSION": "1.2.3\n",
        "README.md": "release source\n",
        "config.json": '{"default": true}\n',
        "items.template": "###items###\n",
        "knxproject_to_openhab.py": "print('runtime')\n",
        "installer/setup.sh": "#!/bin/sh\n",
        "installer/config_migrations.py": "MIGRATIONS = (lambda config: config,)\nLATEST_SCHEMA_VERSION = len(MIGRATIONS)\n",
        "installer/update_contract.json": json.dumps(
            {
                "updater_protocol": 1,
                "config_copy_protocol": 1,
                "accepted_input_schema_versions": [0, 1],
                "output_schema_version": 1,
                "runtime_backward_compatible": True,
            }
        ),
        "web_ui/backend/config.json": '{"auth": {"enabled": true}}\n',
        "tests/test_example.py": "def test_example(): pass\n",
        "docs/screenshots/private.png": "screenshot\n",
        "var/lib/knx_to_openhab/jobs/private.json": '{"private": true}\n',
        "openhab/items/knx.items": "generated output\n",
        ".env": "TOKEN=not-for-release\n",
        "installer/secrets.env": "TOKEN=not-for-release\n",
        "customer.knxproj": "ETS input\n",
    }
    for relative, content in files.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
    environment = os.environ.copy()
    environment.update({"GIT_AUTHOR_NAME": "Release test", "GIT_AUTHOR_EMAIL": "test@example.com"})
    environment.update(
        {"GIT_COMMITTER_NAME": "Release test", "GIT_COMMITTER_EMAIL": "test@example.com"}
    )
    subprocess.run(
        ["git", "-C", str(root), "commit", "-qm", "fixture"],
        env=environment,
        check=True,
    )
    (root / "untracked-secret.txt").write_text("must not ship", encoding="utf-8")
    return root


@pytest.mark.parametrize("version", ["0.1.0", "1.2.3", "2.0.0-rc.1", "1.2.3+build.7"])
def test_accepts_semver_versions(version):
    assert validate_semver(version) == version


@pytest.mark.parametrize(
    "version",
    ["", "v1.2.3", "01.2.3", "1.02.3", "1.2", "1.2.3-01", "1.2.3..rc", "1.2.3/evil"],
)
def test_rejects_invalid_semver_versions(version):
    with pytest.raises(ReleaseArtifactError):
        validate_semver(version)


def test_validates_tag_version_pair():
    assert validate_tag("v1.2.3", "1.2.3") == "1.2.3"

    with pytest.raises(ReleaseArtifactError, match="does not match"):
        validate_tag("v1.2.3", "1.2.4")
    with pytest.raises(ReleaseArtifactError, match="must start with v"):
        validate_tag("1.2.3")


def test_builds_deterministic_archive_and_matching_sha256(tmp_path):
    root = _repository(tmp_path)
    output = tmp_path / "artifacts"

    archive, checksum = build_release(root, "1.2.3", output)
    first_bytes = archive.read_bytes()
    build_release(root, "1.2.3", output)

    assert archive.name == "knx_to_openhab-1.2.3.tar.gz"
    assert checksum.name == "knx_to_openhab-1.2.3.tar.gz.sha256"
    assert archive.read_bytes() == first_bytes
    expected_hash = hashlib.sha256(first_bytes).hexdigest()
    assert checksum.read_text(encoding="ascii") == f"{expected_hash}  {archive.name}\n"

    with tarfile.open(archive, "r:gz") as source:
        members = {member.name: member for member in source.getmembers()}
    prefix = "knx_to_openhab-1.2.3/"
    assert members["knx_to_openhab-1.2.3"].isdir()
    for included in (
        "README.md",
        "config.json",
        "items.template",
        "knxproject_to_openhab.py",
        "installer/setup.sh",
        "installer/update_contract.json",
        "web_ui/backend/config.json",
    ):
        assert prefix + included in members
    for excluded in (
        "tests/test_example.py",
        "docs/screenshots/private.png",
        "var/lib/knx_to_openhab/jobs/private.json",
        "openhab/items/knx.items",
        ".env",
        "installer/secrets.env",
        "customer.knxproj",
        "untracked-secret.txt",
    ):
        assert prefix + excluded not in members
    assert all(not name.startswith("/") and ".." not in Path(name).parts for name in members)


def test_rejects_build_version_that_differs_from_version_file(tmp_path):
    root = _repository(tmp_path)

    with pytest.raises(ReleaseArtifactError, match="VERSION file"):
        build_release(root, "9.9.9", tmp_path / "artifacts")


@pytest.mark.parametrize(
    "change",
    [
        {"output_schema_version": 2},
        {"accepted_input_schema_versions": [0]},
        {"runtime_backward_compatible": False},
        {"updater_protocol": 2},
    ],
)
def test_builder_rejects_incompatible_manifest(tmp_path, change):
    root = _repository(tmp_path)
    path = root / "installer/update_contract.json"
    path.write_text(json.dumps({**json.loads(path.read_text()), **change}))
    with pytest.raises(ReleaseArtifactError, match="contract"):
        build_release(root, "1.2.3", tmp_path / "artifacts")


def test_builder_requires_packaged_manifest(tmp_path):
    root = _repository(tmp_path)
    (root / "installer/update_contract.json").unlink()
    with pytest.raises(ReleaseArtifactError, match="contract"):
        build_release(root, "1.2.3", tmp_path / "artifacts")


def test_builder_checks_schema_without_executing_migration_source(tmp_path):
    root = _repository(tmp_path)
    source = root / "installer/config_migrations.py"
    source.write_text("raise RuntimeError('must not execute')\n" + source.read_text())

    archive, _checksum = build_release(root, "1.2.3", tmp_path / "artifacts")

    with tarfile.open(archive, "r:gz") as packaged:
        manifest = packaged.extractfile("knx_to_openhab-1.2.3/installer/update_contract.json")
        assert json.load(manifest) == {
            "updater_protocol": 1,
            "config_copy_protocol": 1,
            "accepted_input_schema_versions": [0, 1],
            "output_schema_version": 1,
            "runtime_backward_compatible": True,
        }
