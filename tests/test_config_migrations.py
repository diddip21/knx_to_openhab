import json
import os
import stat
from pathlib import Path

import pytest

import installer.config_migrations as config_migrations


def _snapshots(backup_dir: Path) -> list[Path]:
    root = backup_dir / "config-migrations"
    return sorted(path for path in root.iterdir() if path.is_dir()) if root.exists() else []


@pytest.mark.skipif(os.name != "posix", reason="secure snapshot modes require POSIX")
def test_secure_snapshot_root_rejects_symlink(tmp_path):
    source = tmp_path / "config.json"
    source.write_text("{}\n", encoding="utf-8")
    destination = tmp_path / "secure-state"
    target = tmp_path / "redirected-state"
    target.mkdir()
    destination.symlink_to(target, target_is_directory=True)

    with pytest.raises(ValueError, match="symlink"):
        config_migrations.create_snapshot([source], destination, secure=True)


@pytest.mark.skipif(os.name != "posix", reason="secure snapshot modes require POSIX")
def test_secure_snapshot_root_rejects_group_or_world_access(tmp_path):
    source = tmp_path / "config.json"
    source.write_text("{}\n", encoding="utf-8")
    destination = tmp_path / "secure-state"
    destination.mkdir(mode=0o755)
    destination.chmod(0o755)

    with pytest.raises(ValueError, match="private permissions"):
        config_migrations.create_snapshot([source], destination, secure=True)


@pytest.mark.skipif(os.name != "posix", reason="secure snapshot permissions require POSIX")
def test_secure_snapshot_root_rejects_service_writable_ancestor(tmp_path):
    source = tmp_path / "config.json"
    source.write_text("{}\n", encoding="utf-8")
    writable_parent = tmp_path / "service-writable"
    writable_parent.mkdir()
    writable_parent.chmod(0o777)
    private_parent = writable_parent / "config"
    private_parent.mkdir(mode=0o700)
    destination = private_parent / "secure-state"

    with pytest.raises(ValueError, match="service-writable ancestor"):
        config_migrations.create_snapshot([source], destination, secure=True)


@pytest.mark.skipif(os.name != "posix", reason="secure snapshot modes require POSIX")
def test_secure_snapshot_root_and_contents_are_private(tmp_path):
    source = tmp_path / "config.json"
    source.write_text("{}\n", encoding="utf-8")
    destination = tmp_path / "secure-state"

    snapshot = config_migrations.create_snapshot([source], destination, secure=True)

    assert stat.S_IMODE(destination.stat().st_mode) == 0o700
    assert stat.S_IMODE((destination / "config-migrations").stat().st_mode) == 0o700
    assert stat.S_IMODE(snapshot.stat().st_mode) == 0o700
    assert stat.S_IMODE((snapshot / "manifest.json").stat().st_mode) == 0o600


def test_migrates_unversioned_config_additively_and_snapshots_original_bytes(tmp_path):
    config_path = tmp_path / "etc/knx_to_openhab/config.json"
    config_path.parent.mkdir(parents=True)
    original = b'{"port":8085,"auth":{"enabled":true}}\n'
    config_path.write_bytes(original)
    backup_dir = tmp_path / "backups"
    unrelated = backup_dir / "existing-user-backup.tar.gz"
    unrelated.parent.mkdir(parents=True)
    unrelated.write_bytes(b"user data")

    version = config_migrations.migrate_config(config_path, backup_dir)

    assert version == 1
    assert json.loads(config_path.read_text(encoding="utf-8")) == {
        "port": 8085,
        "auth": {"enabled": True},
        "trusted_proxy_hops": 0,
        "session_max_age_seconds": 43200,
        "schema_version": 1,
    }
    snapshots = _snapshots(backup_dir)
    assert len(snapshots) == 1
    manifest = json.loads((snapshots[0] / "manifest.json").read_text(encoding="utf-8"))
    assert [entry["path"] for entry in manifest["files"]] == [str(config_path)]
    saved_copy = snapshots[0] / manifest["files"][0]["snapshot"]
    assert saved_copy.read_bytes() == original
    assert unrelated.read_bytes() == b"user data"


def test_schema_migration_is_idempotent_without_creating_duplicate_snapshots(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text('{"schema_version":1,"port":8123}\n', encoding="utf-8")
    original = config_path.read_bytes()
    backup_dir = tmp_path / "backups"

    assert config_migrations.migrate_config(config_path, backup_dir) == 1
    assert config_path.read_bytes() == original
    assert _snapshots(backup_dir) == []


def test_rejects_future_schema_without_mutation_or_snapshot(tmp_path):
    config_path = tmp_path / "config.json"
    original = b'{"schema_version":42,"port":8085}\n'
    config_path.write_bytes(original)
    backup_dir = tmp_path / "backups"

    with pytest.raises(ValueError, match="newer than supported"):
        config_migrations.migrate_config(config_path, backup_dir)

    assert config_path.read_bytes() == original
    assert _snapshots(backup_dir) == []


def test_migration_failure_restores_original_bytes_from_snapshot(tmp_path, monkeypatch):
    config_path = tmp_path / "config.json"
    original = b'{"port":8085,"auth":{"enabled":true}}\n'
    config_path.write_bytes(original)
    backup_dir = tmp_path / "backups"
    atomic_write = config_migrations._atomic_write

    def write_then_fail(path, contents, mode):
        atomic_write(path, contents, mode)
        raise OSError("injected commit failure")

    monkeypatch.setattr(config_migrations, "_atomic_write", write_then_fail)
    with pytest.raises(OSError, match="injected commit failure"):
        config_migrations.migrate_config(config_path, backup_dir)

    assert config_path.read_bytes() == original
    assert len(_snapshots(backup_dir)) == 1
