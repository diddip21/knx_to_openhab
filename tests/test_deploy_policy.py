import os
import tarfile

import pytest

from web_ui.backend.deploy_policy import (
    DeployPolicyError,
    configured_managed_paths,
    deploy_staged_files,
    provision_managed_files,
    restore_managed_files,
    restrict_service_write_access,
)


def _make_layout(tmp_path):
    root = tmp_path / "openhab"
    stage_root = tmp_path / "jobs" / "job-1" / "staging" / "openhab"
    (root / "items").mkdir(parents=True)
    (stage_root / "items").mkdir(parents=True)
    return root, stage_root


def test_configured_paths_reject_traversal_and_unmanaged_outputs(tmp_path):
    root = tmp_path / "openhab"
    root.mkdir()
    config = {
        "openhab_path": str(root),
        "items_path": str(root / "items" / ".." / "items" / "knx.items"),
    }

    with pytest.raises(DeployPolicyError, match="traversal"):
        configured_managed_paths(config, str(tmp_path))

    config["items_path"] = str(tmp_path / "manual.items")
    with pytest.raises(DeployPolicyError, match="under the OpenHAB"):
        configured_managed_paths(config, str(tmp_path))


def test_yaml_output_is_managed_only_when_yaml_format_has_a_path(tmp_path):
    root = tmp_path / "openhab"
    root.mkdir()
    config = {
        "openhab_path": "openhab",
        "things_path": "openhab/things/knx.things",
        "things_format": "dsl",
        "yaml_path": "",
    }

    _, managed = configured_managed_paths(config, str(tmp_path))
    assert "yaml_path" not in managed

    config["yaml_path"] = "openhab/yaml/knx.yaml"
    _, managed = configured_managed_paths(config, str(tmp_path))
    assert managed["yaml_path"] == "yaml/knx.yaml"


def test_provisioning_creates_only_exact_managed_files(tmp_path):
    root = tmp_path / "openhab"
    root.mkdir()

    provision_managed_files(
        str(root),
        {"items_path": "items/knx.items"},
        os.getuid(),
        os.getgid(),
    )

    generated = root / "items" / "knx.items"
    assert generated.is_file()
    assert generated.stat().st_mode & 0o777 == 0o640
    assert (root / "items").stat().st_mode & 0o020 == 0


def test_provisioning_rejects_symlinked_managed_directory(tmp_path):
    root = tmp_path / "openhab"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (root / "items").symlink_to(outside, target_is_directory=True)

    with pytest.raises(OSError):
        provision_managed_files(
            str(root),
            {"items_path": "items/knx.items"},
            os.getuid(),
            os.getgid(),
        )

    assert list(outside.iterdir()) == []


def test_restrict_write_access_does_not_follow_symlinks(tmp_path):
    root = tmp_path / "openhab"
    outside = tmp_path / "outside"
    root.mkdir(mode=0o777)
    root.chmod(0o777)
    outside.mkdir()
    manual = root / "manual.items"
    manual.write_text("keep contents", encoding="utf-8")
    manual.chmod(0o666)
    external_file = outside / "manual.items"
    external_file.write_text("external", encoding="utf-8")
    external_file.chmod(0o666)
    (root / "linked.items").symlink_to(external_file)

    restrict_service_write_access(str(root), os.getuid() + 1000)

    assert root.stat().st_mode & 0o022 == 0
    assert manual.stat().st_mode & 0o022 == 0
    assert manual.read_text(encoding="utf-8") == "keep contents"
    assert external_file.stat().st_mode & 0o022 == 0o022


def test_deploy_overwrites_only_existing_managed_file_and_keeps_mode(tmp_path):
    root, stage_root = _make_layout(tmp_path)
    target = root / "items" / "knx.items"
    staged = stage_root / "items" / "knx.items"
    target.write_text("old generated content\n", encoding="utf-8")
    staged.write_text("new generated content\n", encoding="utf-8")
    target.chmod(0o640)

    count = deploy_staged_files(
        {str(staged): str(target)},
        str(stage_root.parent),
        str(root),
        {"items_path": "items/knx.items"},
    )

    assert count == 1
    assert target.read_text(encoding="utf-8") == "new generated content\n"
    assert os.stat(target).st_mode & 0o777 == 0o640


def test_deploy_rejects_manually_managed_target_before_writing(tmp_path):
    root, stage_root = _make_layout(tmp_path)
    manual = root / "items" / "manual.items"
    staged = stage_root / "items" / "manual.items"
    manual.write_text("user content\n", encoding="utf-8")
    staged.write_text("generated content\n", encoding="utf-8")

    with pytest.raises(DeployPolicyError, match="not managed"):
        deploy_staged_files(
            {str(staged): str(manual)},
            str(stage_root.parent),
            str(root),
            {"items_path": "items/knx.items"},
        )

    assert manual.read_text(encoding="utf-8") == "user content\n"


def test_deploy_rejects_target_symlink(tmp_path):
    root, stage_root = _make_layout(tmp_path)
    manual = root / "items" / "manual.items"
    target = root / "items" / "knx.items"
    staged = stage_root / "items" / "knx.items"
    manual.write_text("user content\n", encoding="utf-8")
    target.symlink_to(manual.name)
    staged.write_text("generated content\n", encoding="utf-8")

    with pytest.raises((DeployPolicyError, OSError)):
        deploy_staged_files(
            {str(staged): str(target)},
            str(stage_root.parent),
            str(root),
            {"items_path": "items/knx.items"},
        )

    assert manual.read_text(encoding="utf-8") == "user content\n"


def test_deploy_rejects_staged_symlink(tmp_path):
    root, stage_root = _make_layout(tmp_path)
    target = root / "items" / "knx.items"
    staged = stage_root / "items" / "knx.items"
    target.write_text("old generated content\n", encoding="utf-8")
    other = tmp_path / "outside.txt"
    other.write_text("outside data\n", encoding="utf-8")
    staged.symlink_to(other)

    with pytest.raises((DeployPolicyError, OSError)):
        deploy_staged_files(
            {str(staged): str(target)},
            str(stage_root.parent),
            str(root),
            {"items_path": "items/knx.items"},
        )

    assert target.read_text(encoding="utf-8") == "old generated content\n"


def test_rollback_restores_managed_files_without_replacing_manual_files(tmp_path):
    root = tmp_path / "openhab"
    items = root / "items"
    items.mkdir(parents=True)
    target = items / "knx.items"
    manual = items / "manual.items"
    target.write_text("current generated content\n", encoding="utf-8")
    manual.write_text("current manual content\n", encoding="utf-8")
    backup = tmp_path / "backup.tar.gz"
    original = tmp_path / "original"
    (original / "openhab" / "items").mkdir(parents=True)
    (original / "openhab" / "items" / "knx.items").write_text(
        "previous generated content\n", encoding="utf-8"
    )
    (original / "openhab" / "items" / "manual.items").write_text(
        "previous manual content\n", encoding="utf-8"
    )
    with tarfile.open(backup, "w:gz") as archive:
        archive.add(original / "openhab", arcname="openhab")

    restore_managed_files(str(backup), str(root), {"items/knx.items"})

    assert target.read_text(encoding="utf-8") == "previous generated content\n"
    assert manual.read_text(encoding="utf-8") == "current manual content\n"


def test_rollback_skips_managed_files_missing_from_legacy_backup(tmp_path):
    root = tmp_path / "openhab"
    (root / "items").mkdir(parents=True)
    target = root / "items" / "knx.items"
    report = root / "completeness_report.json"
    target.write_text("current generated content\n", encoding="utf-8")
    report.write_text("current report\n", encoding="utf-8")

    original = tmp_path / "original"
    (original / "openhab" / "items").mkdir(parents=True)
    (original / "openhab" / "items" / "knx.items").write_text(
        "legacy generated content\n", encoding="utf-8"
    )
    backup = tmp_path / "legacy-backup.tar.gz"
    with tarfile.open(backup, "w:gz") as archive:
        archive.add(original / "openhab", arcname="openhab")

    restored = restore_managed_files(
        str(backup), str(root), {"items/knx.items", "completeness_report.json"}
    )

    assert restored == 1
    assert target.read_text(encoding="utf-8") == "legacy generated content\n"
    assert report.read_text(encoding="utf-8") == "current report\n"


def test_rollback_recovers_all_live_files_if_a_write_fails(tmp_path, monkeypatch):
    root = tmp_path / "openhab"
    items = root / "items"
    items.mkdir(parents=True)
    first = items / "a.items"
    second = items / "b.items"
    first.write_text("current first file\n", encoding="utf-8")
    second.write_text("current second file\n", encoding="utf-8")

    original = tmp_path / "original"
    original_items = original / "openhab" / "items"
    original_items.mkdir(parents=True)
    (original_items / "a.items").write_text("backup first file\n", encoding="utf-8")
    (original_items / "b.items").write_text("backup second file\n", encoding="utf-8")
    backup = tmp_path / "backup.tar.gz"
    with tarfile.open(backup, "w:gz") as archive:
        archive.add(original / "openhab", arcname="openhab")

    real_write = os.write
    write_count = 0

    def fail_once_after_partial_write(fd, content):
        nonlocal write_count
        write_count += 1
        if write_count == 2:
            real_write(fd, content[:2])
            raise OSError("simulated disk write failure")
        return real_write(fd, content)

    monkeypatch.setattr(os, "write", fail_once_after_partial_write)

    with pytest.raises(OSError, match="simulated disk write failure"):
        restore_managed_files(str(backup), str(root), {"items/a.items", "items/b.items"})

    assert first.read_text(encoding="utf-8") == "current first file\n"
    assert second.read_text(encoding="utf-8") == "current second file\n"
