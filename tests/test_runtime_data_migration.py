import base64
import errno
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

import installer.migrate_runtime_data as migration
from installer.migrate_runtime_data import migrate_runtime_data
from web_ui.backend.auth import hash_password, verify_password
from web_ui.backend.storage import load_config


def _fixture(tmp_path):
    source_root = tmp_path / "opt/knx_to_openhab"
    template_root = tmp_path / "source-template"
    config_dir = tmp_path / "etc/knx_to_openhab"
    data_dir = tmp_path / "var/lib/knx_to_openhab"
    backup_dir = tmp_path / "var/backups/knx_to_openhab"
    (source_root / "web_ui/backend").mkdir(parents=True)
    (template_root / "web_ui/backend").mkdir(parents=True)

    legacy_jobs = source_root / "var/lib/knx_to_openhab"
    legacy_backups = source_root / "var/backups/knx_to_openhab"
    legacy_jobs.mkdir(parents=True)
    legacy_backups.mkdir(parents=True)
    uploaded_file = legacy_jobs / "upload.knxproj"
    uploaded_file.write_text("fixture upload", encoding="utf-8")
    old_staging = legacy_jobs / "job-1/staging/openhab/items/knx.items"
    old_staging.parent.mkdir(parents=True)
    old_staging.write_text("fixture stage", encoding="utf-8")
    old_backup = legacy_backups / "job-1.tar.gz"
    old_backup.write_bytes(b"fixture backup")

    legacy_config = {
        "openhab_path": "/etc/openhab",
        "jobs_dir": "var/lib/knx_to_openhab",
        "backups_dir": "var/backups/knx_to_openhab",
        "bind_host": "127.0.0.1",
        "port": 8085,
        "auth": {"enabled": True, "user": "test-user", "password": "existing-pass"},
        "retention": {"days": 10, "max_backups": 7, "max_backups_size_mb": 90},
        "general": {"auto_place_unknown": True},
    }
    (source_root / "web_ui/backend/config.json").write_text(
        json.dumps(legacy_config), encoding="utf-8"
    )
    (source_root / "config.json").write_text('{"rules":"custom"}\n', encoding="utf-8")
    (template_root / "config.json").write_text('{"rules":"default"}\n', encoding="utf-8")
    (template_root / "web_ui/backend/config.json").write_text(
        json.dumps({"auth": {"enabled": True, "user": "admin", "password": "sample"}}),
        encoding="utf-8",
    )
    jobs = {
        "job-1": {
            "id": "job-1",
            "input": str(uploaded_file),
            "staging_dir": str(old_staging.parent.parent),
            "stage_mapping": {str(old_staging): "/etc/openhab/items/knx.items"},
            "stats": {"knx.items": {"staged_path": str(old_staging)}},
            "backups": [{"name": old_backup.name, "path": str(old_backup)}],
        }
    }
    (legacy_jobs / "jobs.json").write_text(json.dumps(jobs), encoding="utf-8")

    return source_root, template_root, config_dir, data_dir, backup_dir, legacy_jobs, legacy_backups


def _marked_copy_temporary(destination):
    marker = migration._fallback_copy_state_path(destination)
    state = json.loads(marker.read_text(encoding="utf-8"))
    return destination.parent / state["temporary"]


def _run_migration(paths, maintenance_lock_file=None):
    source_root, template_root, config_dir, data_dir, backup_dir, *_ = paths
    paths_file = config_dir.parent / "paths.env"
    arguments = (
        source_root,
        template_root,
        config_dir,
        data_dir,
        backup_dir,
        source_root,
        paths_file,
    )
    if maintenance_lock_file is not None:
        return migrate_runtime_data(*arguments, maintenance_lock_file=maintenance_lock_file)
    return migrate_runtime_data(*arguments)


def test_migration_persists_a_custom_maintenance_lock_path(tmp_path):
    paths = _fixture(tmp_path)
    config_dir = paths[2]
    lock_file = tmp_path / "run locks" / "maintenance.lock"

    result = _run_migration(paths, maintenance_lock_file=lock_file)

    path_file = config_dir.parent / "paths.env"
    assert result["KNXOH_MAINTENANCE_LOCK_FILE"] == lock_file
    assert f'KNXOH_MAINTENANCE_LOCK_FILE="{lock_file}"' in path_file.read_text(encoding="utf-8")


def test_migration_preserves_runtime_config_and_data_outside_install(monkeypatch, tmp_path):
    paths = _fixture(tmp_path)
    source_root, template_root, config_dir, data_dir, backup_dir, old_jobs, old_backups = paths
    web_template_before = (source_root / "web_ui/backend/config.json").read_bytes()

    result = _run_migration(paths)

    migrated_config = json.loads((config_dir / "config.json").read_text(encoding="utf-8"))
    assert migrated_config["bind_host"] == "127.0.0.1"
    assert migrated_config["general"] == {"auto_place_unknown": True}
    assert migrated_config["auth"] == {"enabled": True, "user": "test-user"}
    assert migrated_config["jobs_dir"] == str(data_dir / "jobs")
    assert migrated_config["staging_dir"] == str(data_dir / "staging")
    assert migrated_config["generated_dir"] == str(data_dir / "generated")
    assert migrated_config["backups_dir"] == str(backup_dir)
    assert json.loads((data_dir / "generator.json").read_text(encoding="utf-8")) == {
        "rules": "custom"
    }
    assert (config_dir / "secrets.env").stat().st_mode & 0o777 == 0o640
    secret_line = (config_dir / "secrets.env").read_text(encoding="utf-8").strip()
    assert secret_line.startswith("KNXOH_UI_PASSWORD_HASH_B64=")
    password_hash = base64.b64decode(secret_line.split("=", 1)[1]).decode()
    assert verify_password(password_hash, "existing-pass")
    assert (data_dir / "jobs/upload.knxproj").read_text(encoding="utf-8") == "fixture upload"
    assert (data_dir / "jobs/job-1/staging/openhab/items/knx.items").is_file()
    assert (backup_dir / "job-1.tar.gz").read_bytes() == b"fixture backup"
    assert not old_jobs.exists()
    assert not old_backups.exists()
    assert json.loads((data_dir / "jobs/jobs.json").read_text(encoding="utf-8"))["job-1"][
        "input"
    ] == str(data_dir / "jobs/upload.knxproj")
    assert result["KNXOH_CONFIG_DIR"] == config_dir
    assert result["KNXOH_DATA_DIR"] == data_dir
    assert (config_dir.parent / "paths.env").is_file()
    assert (source_root / "web_ui/backend/config.json").read_bytes() == web_template_before
    assert (source_root / "config.json").read_text(encoding="utf-8") == (
        template_root / "config.json"
    ).read_text(encoding="utf-8")

    monkeypatch.setenv("KNXOH_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("KNXOH_DATA_DIR", str(data_dir))
    monkeypatch.setenv("KNXOH_BACKUP_DIR", str(backup_dir))
    monkeypatch.setenv("KNXOH_INSTALL_DIR", str(source_root))
    monkeypatch.setenv("KNXOH_PATHS_FILE", str(config_dir.parent / "paths.env"))
    loaded = load_config(source_root)
    assert verify_password(loaded["auth"]["password_hash"], "existing-pass")
    assert "password" not in loaded["auth"]
    assert loaded["jobs_dir"] == str(data_dir / "jobs")
    assert loaded["backups_dir"] == str(backup_dir)


@pytest.mark.parametrize("credential_source", ["config", "legacy_secret", "hashed_secret"])
def test_migration_discards_shipped_default_for_secure_replacement(tmp_path, credential_source):
    paths = _fixture(tmp_path)
    source_root, _, config_dir, _, _, *_ = paths
    legacy_config = source_root / "web_ui/backend/config.json"
    config = json.loads(legacy_config.read_text(encoding="utf-8"))
    if credential_source == "config":
        config["auth"]["password"] = "logihome"
    else:
        config["auth"].pop("password")
        config_dir.mkdir(parents=True, exist_ok=True)
        if credential_source == "legacy_secret":
            encoded = base64.b64encode(b"logihome").decode("ascii")
            secret_value = f"KNXOH_UI_PASSWORD_B64={encoded}\n"
        else:
            encoded = base64.b64encode(hash_password("logihome").encode()).decode("ascii")
            secret_value = f"KNXOH_UI_PASSWORD_HASH_B64={encoded}\n"
        (config_dir / "secrets.env").write_text(secret_value, encoding="utf-8")
    legacy_config.write_text(json.dumps(config), encoding="utf-8")

    _run_migration(paths)

    migrated = json.loads((config_dir / "config.json").read_text(encoding="utf-8"))
    secrets = (config_dir / "secrets.env").read_text(encoding="utf-8")
    assert "password" not in migrated["auth"]
    assert "KNXOH_UI_PASSWORD_HASH_B64=" not in secrets
    assert "KNXOH_UI_PASSWORD_B64=" not in secrets
    assert "logihome" not in secrets


def test_migration_is_idempotent_and_keeps_existing_external_values(tmp_path):
    paths = _fixture(tmp_path)
    _run_migration(paths)
    config_dir = paths[2]
    secret_file = config_dir / "secrets.env"
    secret_file.write_text("KNXOH_UI_PASSWORD_B64=bmV3LXBhc3M=\n", encoding="utf-8")

    _run_migration(paths)

    secret_line = secret_file.read_text(encoding="utf-8").strip()
    assert secret_line.startswith("KNXOH_UI_PASSWORD_HASH_B64=")
    password_hash = base64.b64decode(secret_line.split("=", 1)[1]).decode()
    assert verify_password(password_hash, "new-pass")
    assert json.loads((paths[3] / "generator.json").read_text(encoding="utf-8")) == {
        "rules": "custom"
    }
    assert (paths[3] / "jobs/upload.knxproj").is_file()
    assert (paths[4] / "job-1.tar.gz").is_file()


def test_migration_moves_existing_config_dir_generator_file_to_writable_data_dir(tmp_path):
    paths = _fixture(tmp_path)
    config_dir = paths[2]
    config_dir.mkdir(parents=True)
    legacy_generator = config_dir / "generator.json"
    legacy_generator.write_text('{"rules":"external custom"}\n', encoding="utf-8")

    _run_migration(paths)

    assert json.loads((paths[3] / "generator.json").read_text(encoding="utf-8")) == {
        "rules": "external custom"
    }
    assert legacy_generator.read_text(encoding="utf-8") == '{"rules":"external custom"}\n'


def test_failed_path_publication_keeps_legacy_sources_and_can_retry(monkeypatch, tmp_path):
    paths = _fixture(tmp_path)
    _, _, config_dir, data_dir, _, old_jobs, old_backups = paths
    paths_file = config_dir.parent / "paths.env"
    original_path_writer = migration._write_paths_file

    def fail_path_write(*_args):
        raise OSError("simulated config filesystem failure")

    monkeypatch.setattr(migration, "_write_paths_file", fail_path_write)
    with pytest.raises(OSError, match="simulated config filesystem failure"):
        _run_migration(paths)

    # The original installation data and its job index remain intact until
    # path publication succeeds, so a retry can still identify every source.
    copied_job = json.loads((data_dir / "jobs/jobs.json").read_text(encoding="utf-8"))["job-1"]
    assert copied_job["input"] == str(old_jobs / "upload.knxproj")
    assert old_jobs.is_dir()
    assert old_backups.is_dir()
    copied_config = json.loads((config_dir / "config.json").read_text(encoding="utf-8"))
    assert copied_config["jobs_dir"] == "var/lib/knx_to_openhab"
    assert "password" not in copied_config["auth"]
    secret_line = (config_dir / "secrets.env").read_text(encoding="utf-8").strip()
    assert secret_line.startswith("KNXOH_UI_PASSWORD_HASH_B64=")
    password_hash = base64.b64decode(secret_line.split("=", 1)[1]).decode("utf-8")
    assert verify_password(password_hash, "existing-pass")
    assert paths_file.exists() is False

    monkeypatch.setattr(migration, "_write_paths_file", original_path_writer)
    _run_migration(paths)

    assert not old_jobs.exists()
    assert not old_backups.exists()
    assert json.loads((config_dir / "config.json").read_text(encoding="utf-8"))["jobs_dir"] == str(
        data_dir / "jobs"
    )
    retried_job = json.loads((data_dir / "jobs/jobs.json").read_text(encoding="utf-8"))["job-1"]
    assert retried_job["input"] == str(data_dir / "jobs/upload.knxproj")


def test_interrupted_file_copy_keeps_legacy_data_and_can_retry(monkeypatch, tmp_path):
    paths = _fixture(tmp_path)
    _, _, config_dir, data_dir, backup_dir, old_jobs, old_backups = paths
    original_copy2 = migration.shutil.copy2

    def fail_after_partial_write(source, destination, *args, **kwargs):
        if Path(source).name == "upload.knxproj":
            Path(destination).write_bytes(b"partial")
            raise OSError("simulated interrupted copy")
        return original_copy2(source, destination, *args, **kwargs)

    monkeypatch.setattr(migration.shutil, "copy2", fail_after_partial_write)
    with pytest.raises(OSError, match="simulated interrupted copy"):
        _run_migration(paths)

    assert (old_jobs / "upload.knxproj").read_text(encoding="utf-8") == "fixture upload"
    assert old_backups.is_dir()
    assert not (data_dir / "jobs/upload.knxproj").exists()
    assert not list((data_dir / "jobs").glob(".knxoh-copy-*"))
    assert not (config_dir.parent / "paths.env").exists()

    monkeypatch.setattr(migration.shutil, "copy2", original_copy2)
    _run_migration(paths)

    assert (data_dir / "jobs/upload.knxproj").read_text(encoding="utf-8") == "fixture upload"
    assert (backup_dir / "job-1.tar.gz").read_bytes() == b"fixture backup"
    assert not old_jobs.exists()
    assert not old_backups.exists()


def test_copy_retry_preserves_unrelated_file_with_temporary_prefix(tmp_path):
    paths = _fixture(tmp_path)
    target_jobs = paths[3] / "jobs"
    target_jobs.mkdir(parents=True)
    unrelated = target_jobs / ".knxoh-copy-unrelated"
    unrelated.write_text("fixture upload", encoding="utf-8")

    _run_migration(paths)

    assert unrelated.read_text(encoding="utf-8") == "fixture upload"
    assert (target_jobs / "upload.knxproj").read_text(encoding="utf-8") == "fixture upload"


def test_copy_temporary_collision_uses_a_new_name(monkeypatch, tmp_path):
    paths = _fixture(tmp_path)
    target = paths[3] / "jobs" / "upload.knxproj"
    target.parent.mkdir(parents=True)
    prefix = migration._copy_temporary_prefix(target)
    collision = target.parent / f"{prefix}collision"
    collision.write_text("valuable unrelated data", encoding="utf-8")

    original_mkstemp = migration.tempfile.mkstemp
    original_get_candidate_names = migration.tempfile._get_candidate_names
    injected_collision = False

    def inject_copy_temp_collision(*args, **kwargs):
        nonlocal injected_collision
        if kwargs.get("prefix") == prefix and not injected_collision:
            injected_collision = True
            monkeypatch.setattr(
                migration.tempfile,
                "_get_candidate_names",
                lambda: iter(("collision", "available")),
            )
            try:
                return original_mkstemp(*args, **kwargs)
            finally:
                monkeypatch.setattr(
                    migration.tempfile,
                    "_get_candidate_names",
                    original_get_candidate_names,
                )
        return original_mkstemp(*args, **kwargs)

    monkeypatch.setattr(migration.tempfile, "mkstemp", inject_copy_temp_collision)

    _run_migration(paths)

    assert injected_collision
    assert collision.read_text(encoding="utf-8") == "valuable unrelated data"
    assert target.read_text(encoding="utf-8") == "fixture upload"
    assert list(target.parent.glob(f"{prefix}*")) == [collision]


def test_copy_publication_works_without_hard_links(monkeypatch, tmp_path):
    paths = _fixture(tmp_path)

    def reject_hard_links(*_args):
        raise OSError(errno.EPERM, "hard links are disabled")

    def fail_if_a_second_copy_is_needed(*_args):
        raise AssertionError("the no-replace rename should publish the temporary file")

    monkeypatch.setattr(migration.os, "link", reject_hard_links)
    monkeypatch.setattr(migration, "_copy_no_replace", fail_if_a_second_copy_is_needed)

    _run_migration(paths)

    assert (paths[3] / "jobs/upload.knxproj").read_text(encoding="utf-8") == "fixture upload"
    assert (paths[4] / "job-1.tar.gz").read_bytes() == b"fixture backup"
    assert not paths[5].exists()
    assert not paths[6].exists()


def test_no_hard_link_fallback_does_not_replace_a_racing_target(monkeypatch, tmp_path):
    paths = _fixture(tmp_path)
    original_link = migration.os.link
    raced_target = paths[3] / "jobs/upload.knxproj"

    def race_upload_target(source, destination):
        if Path(destination).name == "upload.knxproj":
            Path(destination).write_text("concurrent data", encoding="utf-8")
            raise OSError(errno.EPERM, "hard links are disabled")
        return original_link(source, destination)

    monkeypatch.setattr(migration.os, "link", race_upload_target)

    with pytest.raises(FileExistsError):
        _run_migration(paths)

    assert raced_target.read_text(encoding="utf-8") == "concurrent data"
    assert (paths[5] / "upload.knxproj").read_text(encoding="utf-8") == "fixture upload"
    assert not list(raced_target.parent.glob(".knxoh-copy-*"))


def test_no_hard_link_fallback_revalidates_target_before_success(monkeypatch, tmp_path):
    paths = _fixture(tmp_path)
    target = paths[3] / "jobs/upload.knxproj"
    original_copyfileobj = migration.shutil.copyfileobj

    def reject_hard_links(*_args):
        raise OSError(errno.EPERM, "hard links are disabled")

    def no_replace_rename_unavailable(*_args):
        raise OSError(errno.ENOTSUP, "no-replace rename is unavailable")

    def replace_target_after_copy(source, destination, *args, **kwargs):
        result = original_copyfileobj(source, destination, *args, **kwargs)
        if Path(source.name).name.startswith(migration._copy_temporary_prefix(target)):
            target.unlink()
            target.write_text("concurrent data", encoding="utf-8")
        return result

    monkeypatch.setattr(migration.os, "link", reject_hard_links)
    monkeypatch.setattr(migration, "_rename_no_replace", no_replace_rename_unavailable)
    monkeypatch.setattr(migration.shutil, "copyfileobj", replace_target_after_copy)

    with pytest.raises(FileExistsError, match="changed before publication completed"):
        _run_migration(paths)

    assert target.read_text(encoding="utf-8") == "concurrent data"
    assert (paths[5] / "upload.knxproj").read_text(encoding="utf-8") == "fixture upload"


def test_no_hard_link_fallback_does_not_change_replaced_target_metadata(monkeypatch, tmp_path):
    paths = _fixture(tmp_path)
    target = paths[3] / "jobs/upload.knxproj"
    original_copy_metadata = migration._copy_fallback_metadata
    competing_metadata = {}

    def reject_hard_links(*_args):
        raise OSError(errno.EPERM, "hard links are disabled")

    def no_replace_rename_unavailable(*_args):
        raise OSError(errno.ENOTSUP, "no-replace rename is unavailable")

    def replace_target_before_metadata(source, destination_descriptor):
        if Path(source.name).name.startswith(migration._copy_temporary_prefix(target)):
            target.unlink()
            target.write_text("concurrent data", encoding="utf-8")
            target.chmod(0o600)
            os.utime(target, ns=(1_000_000_000, 1_000_000_000))
            target_info = target.stat()
            competing_metadata["mode"] = target_info.st_mode & 0o777
            competing_metadata["mtime_ns"] = target_info.st_mtime_ns
        original_copy_metadata(source, destination_descriptor)

    monkeypatch.setattr(migration.os, "link", reject_hard_links)
    monkeypatch.setattr(migration, "_rename_no_replace", no_replace_rename_unavailable)
    monkeypatch.setattr(migration, "_copy_fallback_metadata", replace_target_before_metadata)

    with pytest.raises(FileExistsError, match="changed before publication completed"):
        _run_migration(paths)

    target_info = target.stat()
    assert target.read_text(encoding="utf-8") == "concurrent data"
    assert target_info.st_mode & 0o777 == competing_metadata["mode"] == 0o600
    assert target_info.st_mtime_ns == competing_metadata["mtime_ns"]
    assert (paths[5] / "upload.knxproj").read_text(encoding="utf-8") == "fixture upload"


def test_no_hard_link_fallback_cleans_up_an_interrupted_copy(monkeypatch, tmp_path):
    paths = _fixture(tmp_path)
    original_copyfileobj = migration.shutil.copyfileobj

    def reject_hard_links(*_args):
        raise OSError(errno.EPERM, "hard links are disabled")

    def no_replace_rename_unavailable(*_args):
        raise OSError(errno.ENOTSUP, "no-replace rename is unavailable")

    def fail_after_partial_write(source, destination, *args, **kwargs):
        if Path(source.name).name.startswith(".knxoh-copy-"):
            destination.write(b"partial")
            raise OSError("simulated fallback copy interruption")
        return original_copyfileobj(source, destination, *args, **kwargs)

    monkeypatch.setattr(migration.os, "link", reject_hard_links)
    monkeypatch.setattr(migration, "_rename_no_replace", no_replace_rename_unavailable)
    monkeypatch.setattr(migration.shutil, "copyfileobj", fail_after_partial_write)

    with pytest.raises(OSError, match="simulated fallback copy interruption"):
        _run_migration(paths)

    assert (paths[5] / "upload.knxproj").read_text(encoding="utf-8") == "fixture upload"
    assert not (paths[3] / "jobs/upload.knxproj").exists()
    assert not list((paths[3] / "jobs").glob(".knxoh-copy-*"))


def test_no_hard_link_fallback_cleans_up_on_keyboard_interrupt(monkeypatch, tmp_path):
    paths = _fixture(tmp_path)

    def reject_hard_links(*_args):
        raise OSError(errno.EPERM, "hard links are disabled")

    def no_replace_rename_unavailable(*_args):
        raise OSError(errno.ENOTSUP, "no-replace rename is unavailable")

    def interrupt_after_partial_write(_source, destination, *_args, **_kwargs):
        destination.write(b"partial")
        raise KeyboardInterrupt

    monkeypatch.setattr(migration.os, "link", reject_hard_links)
    monkeypatch.setattr(migration, "_rename_no_replace", no_replace_rename_unavailable)
    monkeypatch.setattr(migration.shutil, "copyfileobj", interrupt_after_partial_write)

    with pytest.raises(KeyboardInterrupt):
        _run_migration(paths)

    assert (paths[5] / "upload.knxproj").read_text(encoding="utf-8") == "fixture upload"
    assert not (paths[3] / "jobs/upload.knxproj").exists()
    assert not list((paths[3] / "jobs").glob(".knxoh-copy-*"))


@pytest.mark.parametrize(
    "crash_point",
    [
        "marker-initial-write",
        "temporary-created",
        "fallback-prepared",
        "fallback-copying",
        "partial-copy",
        "initial-copy",
    ],
)
def test_interrupted_fallback_copy_is_recovered_or_preserved(tmp_path, crash_point):
    paths = _fixture(tmp_path)
    source = paths[5]
    destination = paths[3] / "jobs"
    ready = tmp_path / "copy-ready"
    repository_root = Path(__file__).resolve().parents[1]
    child_code = "\n".join(
        (
            "import errno, json, sys, time",
            "from pathlib import Path",
            "import installer.migrate_runtime_data as migration",
            "crash_point = sys.argv[4]",
            "ready_path = Path(sys.argv[3])",
            "target = Path(sys.argv[2]) / 'upload.knxproj'",
            "marker = migration._fallback_copy_state_path(target)",
            "temporary_prefix = migration._copy_temporary_prefix(target)",
            "original_replace = migration.os.replace",
            "original_open = migration.os.open",
            "def interrupt_temporary_creation(path, flags, *args, **kwargs):",
            "    descriptor = original_open(path, flags, *args, **kwargs)",
            "    if crash_point == 'temporary-created' and Path(path).name.startswith(temporary_prefix):",
            "        ready_path.write_text('ready', encoding='utf-8')",
            "        time.sleep(60)",
            "    return descriptor",
            "def marker_state(path):",
            "    try:",
            "        return json.loads(Path(path).read_text(encoding='utf-8'))",
            "    except (OSError, ValueError):",
            "        return {}",
            "def interrupt_marker_update(source, destination):",
            "    if Path(destination) == marker:",
            "        state = marker_state(source)",
            "        should_interrupt = state.get('phase') == crash_point",
            "        should_interrupt = should_interrupt or (crash_point == 'marker-initial-write' and state.get('phase') == 'staging')",
            "        if should_interrupt:",
            "            ready_path.write_text('ready', encoding='utf-8')",
            "            time.sleep(60)",
            "    return original_replace(source, destination)",
            "def reject_hard_links(*args):",
            "    raise OSError(errno.EPERM, 'hard links are disabled')",
            "def no_replace_rename(*args):",
            "    raise OSError(errno.ENOTSUP, 'no-replace rename is unavailable')",
            "original_copyfileobj = migration.shutil.copyfileobj",
            "def interrupt_copy(source, destination, *args, **kwargs):",
            "    if crash_point == 'partial-copy' and Path(source.name).name.startswith(temporary_prefix):",
            "        destination.write(b'partial')",
            "        destination.flush()",
            "        ready_path.write_text('ready', encoding='utf-8')",
            "        time.sleep(60)",
            "    return original_copyfileobj(source, destination, *args, **kwargs)",
            "original_copy2 = migration.shutil.copy2",
            "def interrupt_initial_copy(source, destination, *args, **kwargs):",
            "    if crash_point == 'initial-copy' and Path(destination).name.startswith(temporary_prefix):",
            "        Path(destination).write_bytes(b'partial')",
            "        ready_path.write_text('ready', encoding='utf-8')",
            "        time.sleep(60)",
            "    return original_copy2(source, destination, *args, **kwargs)",
            "migration.os.link = reject_hard_links",
            "migration._rename_no_replace = no_replace_rename",
            "migration.os.replace = interrupt_marker_update",
            "migration.os.open = interrupt_temporary_creation",
            "migration.shutil.copyfileobj = interrupt_copy",
            "migration.shutil.copy2 = interrupt_initial_copy",
            "migration._copy_missing_tree(Path(sys.argv[1]), Path(sys.argv[2]))",
        )
    )
    process = subprocess.Popen(
        [
            sys.executable,
            "-c",
            child_code,
            str(source),
            str(destination),
            str(ready),
            crash_point,
        ],
        cwd=repository_root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    deadline = time.monotonic() + 10
    while not ready.exists() and process.poll() is None and time.monotonic() < deadline:
        time.sleep(0.01)
    if not ready.exists():
        process.kill()
        stdout, stderr = process.communicate(timeout=10)
        pytest.fail(f"migration child did not reach {crash_point}: {stdout}{stderr}")

    partial_target = destination / "upload.knxproj"
    temporary_prefix = migration._copy_temporary_prefix(partial_target)
    temporary_paths = list(destination.glob(f"{temporary_prefix}*"))
    assert len(temporary_paths) == 1
    interrupted_temporary = temporary_paths[0]
    try:
        if crash_point in {"marker-initial-write", "fallback-prepared"}:
            assert not partial_target.exists()
        elif crash_point == "fallback-copying":
            assert partial_target.read_bytes() == b""
        elif crash_point == "partial-copy":
            assert partial_target.read_bytes() == b"partial"
        elif crash_point == "temporary-created":
            assert not partial_target.exists()
            assert interrupted_temporary.read_bytes() == b""
        if crash_point == "initial-copy":
            assert not partial_target.exists()
            assert interrupted_temporary.read_bytes() == b"partial"
        if crash_point == "temporary-created":
            assert not migration._fallback_copy_state_path(partial_target).exists()
        else:
            assert migration._fallback_copy_state_path(partial_target).is_file()
    finally:
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=10)

    marker_temps = {
        path: path.read_bytes() for path in destination.glob(".knxoh-copy-state-*.tmp-*")
    }

    if crash_point == "marker-initial-write":
        with pytest.raises(ValueError, match="fallback-copy marker is invalid"):
            _run_migration(paths)
        assert migration._fallback_copy_state_path(partial_target).read_bytes() == b""
        assert interrupted_temporary.read_bytes() == b""
        assert paths[5].exists()
        assert all(path.read_bytes() == content for path, content in marker_temps.items())
        return

    if crash_point == "temporary-created":
        _run_migration(paths)
        assert partial_target.read_text(encoding="utf-8") == "fixture upload"
        assert interrupted_temporary.read_bytes() == b""
        assert not migration._fallback_copy_state_path(partial_target).exists()
        assert not paths[5].exists()
        assert all(path.read_bytes() == content for path, content in marker_temps.items())
        return

    if crash_point in {"fallback-prepared", "initial-copy"}:
        with pytest.raises(FileExistsError, match="tracked temporary without a destination"):
            _run_migration(paths)
        assert not partial_target.exists()
        assert migration._fallback_copy_state_path(partial_target).is_file()
        assert interrupted_temporary.exists()
        if crash_point == "initial-copy":
            assert interrupted_temporary.read_bytes() == b"partial"
        else:
            assert interrupted_temporary.read_bytes() == b"fixture upload"
        assert source.joinpath("upload.knxproj").read_text(encoding="utf-8") == "fixture upload"
        assert all(path.read_bytes() == content for path, content in marker_temps.items())
        return

    if crash_point == "fallback-copying":
        with pytest.raises(FileExistsError, match="without a recorded identity"):
            _run_migration(paths)
        assert partial_target.read_bytes() == b""
        assert migration._fallback_copy_state_path(partial_target).is_file()
        assert _marked_copy_temporary(partial_target).read_bytes() == b"fixture upload"
        assert paths[5].exists()
        assert all(path.read_bytes() == content for path, content in marker_temps.items())
        return

    if crash_point == "partial-copy":
        with pytest.raises(FileExistsError, match="incomplete or ambiguous target"):
            _run_migration(paths)
        assert partial_target.read_bytes() == b"partial"
        assert migration._fallback_copy_state_path(partial_target).is_file()
        assert _marked_copy_temporary(partial_target).read_bytes() == b"fixture upload"
        assert source.joinpath("upload.knxproj").read_text(encoding="utf-8") == "fixture upload"
        assert all(path.read_bytes() == content for path, content in marker_temps.items())
        return

    _run_migration(paths)

    assert partial_target.read_text(encoding="utf-8") == "fixture upload"
    assert not migration._fallback_copy_state_path(partial_target).exists()
    assert all(path.read_bytes() == content for path, content in marker_temps.items())
    assert not list(destination.glob(f"{temporary_prefix}*"))
    assert not paths[5].exists()


def test_fallback_copying_recovery_preserves_target_with_reused_inode(tmp_path):
    paths = _fixture(tmp_path)
    source = paths[5] / "upload.knxproj"
    target = paths[3] / "jobs" / "upload.knxproj"
    target.parent.mkdir(parents=True)
    temporary = target.parent / f"{migration._copy_temporary_prefix(target)}recovery"
    temporary.write_bytes(source.read_bytes())
    temporary_info = temporary.stat()
    target.write_bytes(b"competing file after inode reuse")
    target_info = target.stat()
    marker = migration._fallback_copy_state_path(target)
    marker.write_text(
        json.dumps(
            {
                "name": target.name,
                "temporary": temporary.name,
                "temporary_identity": {
                    "device": temporary_info.st_dev,
                    "inode": temporary_info.st_ino,
                },
                "destination_identity": {
                    "device": target_info.st_dev,
                    "inode": target_info.st_ino,
                },
                "phase": "fallback-copying",
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(FileExistsError, match="incomplete or ambiguous target"):
        _run_migration(paths)

    assert target.read_bytes() == b"competing file after inode reuse"
    assert marker.is_file()
    assert temporary.read_bytes() == source.read_bytes()
    assert source.exists()


def test_tracked_temporary_recovery_preserves_file_with_reused_inode(tmp_path):
    paths = _fixture(tmp_path)
    source = paths[5] / "upload.knxproj"
    target = paths[3] / "jobs" / "upload.knxproj"
    target.parent.mkdir(parents=True)
    temporary = target.parent / f"{migration._copy_temporary_prefix(target)}reused"
    temporary.write_bytes(b"competing temporary after inode reuse")
    temporary_info = temporary.stat()
    marker = migration._fallback_copy_state_path(target)
    marker.write_text(
        json.dumps(
            {
                "name": target.name,
                "temporary": temporary.name,
                "temporary_identity": {
                    "device": temporary_info.st_dev,
                    "inode": temporary_info.st_ino,
                },
                "phase": "staging",
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(FileExistsError, match="tracked temporary without a destination"):
        _run_migration(paths)

    assert not target.exists()
    assert temporary.read_bytes() == b"competing temporary after inode reuse"
    assert marker.is_file()
    assert source.exists()


@pytest.mark.parametrize("contents", [b"unrelated data", b""])
def test_unrecorded_staging_file_is_preserved(tmp_path, contents):
    paths = _fixture(tmp_path)
    target = paths[3] / "jobs" / "upload.knxproj"
    target.parent.mkdir(parents=True)
    temporary = target.parent / f"{migration._copy_temporary_prefix(target)}unrelated"
    marker = migration._fallback_copy_state_path(target)
    temporary.write_bytes(contents)
    temporary.chmod(0o600)
    marker.write_text(
        json.dumps(
            {
                "name": target.name,
                "temporary": temporary.name,
                "phase": "staging",
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(FileExistsError, match="unverified temporary file"):
        _run_migration(paths)

    assert temporary.read_bytes() == contents
    assert paths[5].exists()


def test_invalid_marker_collision_is_preserved(tmp_path):
    paths = _fixture(tmp_path)
    target = paths[3] / "jobs" / "upload.knxproj"
    target.parent.mkdir(parents=True)
    marker = migration._fallback_copy_state_path(target)
    marker.write_text("valuable unrelated marker", encoding="utf-8")

    with pytest.raises(ValueError, match="fallback-copy marker is invalid"):
        _run_migration(paths)

    assert marker.read_text(encoding="utf-8") == "valuable unrelated marker"
    assert not target.exists()
    assert paths[5].exists()


@pytest.mark.parametrize("competing_content", [b"", b"fixture"])
def test_fallback_prepared_recovery_preserves_unverified_competing_target(
    tmp_path, competing_content
):
    paths = _fixture(tmp_path)
    source = paths[5] / "upload.knxproj"
    target = paths[3] / "jobs" / "upload.knxproj"
    target.parent.mkdir(parents=True)
    temporary = target.parent / f"{migration._copy_temporary_prefix(target)}recovery"
    temporary.write_bytes(source.read_bytes())
    temporary_info = temporary.stat()
    target.write_bytes(competing_content)
    marker = migration._fallback_copy_state_path(target)
    marker.write_text(
        json.dumps(
            {
                "name": target.name,
                "temporary": temporary.name,
                "temporary_identity": {
                    "device": temporary_info.st_dev,
                    "inode": temporary_info.st_ino,
                },
                "phase": "fallback-prepared",
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(FileExistsError, match="without a recorded identity"):
        _run_migration(paths)

    assert target.read_bytes() == competing_content
    assert marker.is_file()
    assert temporary.read_bytes() == source.read_bytes()
    assert source.exists()


def test_unrelated_marker_state_temporary_is_preserved(tmp_path):
    paths = _fixture(tmp_path)
    target = paths[3] / "jobs" / "upload.knxproj"
    target.parent.mkdir(parents=True)
    marker = migration._fallback_copy_state_path(target)
    unrelated_temporary = target.parent / f"{marker.name}.tmp-unrelated"
    unrelated_temporary.write_text("valuable unrelated state", encoding="utf-8")

    _run_migration(paths)

    assert unrelated_temporary.read_text(encoding="utf-8") == "valuable unrelated state"


def test_migration_copies_valid_long_filename(tmp_path):
    paths = _fixture(tmp_path)
    old_jobs = paths[5]
    filename = "a" * 250
    (old_jobs / filename).write_text("long-name fixture", encoding="utf-8")

    _run_migration(paths)

    copied = paths[3] / "jobs" / filename
    assert copied.read_text(encoding="utf-8") == "long-name fixture"


def test_migration_refuses_conflicting_existing_data_without_deleting_legacy(tmp_path):
    paths = _fixture(tmp_path)
    legacy_jobs = paths[5]
    target_jobs = paths[3] / "jobs"
    target_jobs.mkdir(parents=True)
    (target_jobs / "upload.knxproj").write_text("different data", encoding="utf-8")

    with pytest.raises(FileExistsError, match="conflicts"):
        _run_migration(paths)

    assert legacy_jobs.exists()
    assert (legacy_jobs / "upload.knxproj").read_text(encoding="utf-8") == "fixture upload"


@pytest.mark.parametrize("unsafe_path", ["/", "/etc", "/usr", "/var", "/home", "/root"])
def test_migration_refuses_system_directories_as_legacy_data(tmp_path, unsafe_path):
    paths = _fixture(tmp_path)
    source_root = paths[0]
    config_path = source_root / "web_ui/backend/config.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["jobs_dir"] = unsafe_path
    config_path.write_text(json.dumps(config), encoding="utf-8")

    with pytest.raises(ValueError, match="Refusing to migrate"):
        _run_migration(paths)

    assert paths[5].exists()


def test_migration_refuses_symlinked_legacy_tree(tmp_path):
    paths = _fixture(tmp_path)
    source_root = paths[0]
    real_jobs = paths[5]
    link = source_root / "linked-jobs"
    link.symlink_to(real_jobs, target_is_directory=True)
    config_path = source_root / "web_ui/backend/config.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["jobs_dir"] = str(link)
    config_path.write_text(json.dumps(config), encoding="utf-8")

    with pytest.raises(ValueError, match="symlink"):
        _run_migration(paths)

    assert real_jobs.exists()


def test_migration_refuses_broad_application_subdirectory_as_runtime_data(tmp_path):
    paths = _fixture(tmp_path)
    source_root = paths[0]
    web_ui = source_root / "web_ui"
    config_path = source_root / "web_ui/backend/config.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["jobs_dir"] = str(web_ui)
    config_path.write_text(json.dumps(config), encoding="utf-8")

    with pytest.raises(ValueError, match="unexpected in-application jobs directory"):
        _run_migration(paths)

    assert web_ui.is_dir()
    assert config_path.is_file()


def test_saved_paths_round_trip_dollar_signs_and_special_characters(tmp_path):
    path = tmp_path / "paths with $dollar and 'quotes' \\slashes.env"

    migration._write_paths_file(
        path,
        {"KNXOH_INSTALL_DIR": tmp_path / "app $cash 'quoted' \\path"},
    )

    import shlex

    line = path.read_text(encoding="utf-8").splitlines()[1]
    key, serialized = line.split("=", 1)
    assert key == "KNXOH_INSTALL_DIR"
    assert shlex.split(serialized) == [str(tmp_path / "app $cash 'quoted' \\path")]


def test_backup_cleanup_uses_canonical_external_paths(tmp_path):
    config_dir = tmp_path / "etc/knx_to_openhab"
    data_dir = tmp_path / "var/lib/knx_to_openhab"
    backup_dir = tmp_path / "var/backups/knx_to_openhab"
    config_dir.mkdir(parents=True)
    backup_dir.mkdir(parents=True)
    (config_dir / "config.json").write_text(
        json.dumps(
            {
                "jobs_dir": str(data_dir / "jobs"),
                "staging_dir": str(data_dir / "staging"),
                "generated_dir": str(data_dir / "generated"),
                "backups_dir": str(backup_dir),
                "auth": {"enabled": False},
                "retention": {"days": 100, "max_backups": 1, "max_backups_size_mb": 50},
                "general": {},
            }
        ),
        encoding="utf-8",
    )
    older = backup_dir / "older.tar.gz"
    newest = backup_dir / "newest.tar.gz"
    older.write_bytes(b"old")
    newest.write_bytes(b"new")
    now = time.time()
    os.utime(older, (now - 20, now - 20))
    os.utime(newest, (now, now))

    environment = os.environ.copy()
    environment.update(
        {
            "KNXOH_CONFIG_DIR": str(config_dir),
            "KNXOH_DATA_DIR": str(data_dir),
            "KNXOH_BACKUP_DIR": str(backup_dir),
            "KNXOH_INSTALL_DIR": str(tmp_path / "opt/knx_to_openhab"),
            "KNXOH_PATHS_FILE": str(tmp_path / "missing-paths.env"),
        }
    )
    script = Path(__file__).resolve().parents[1] / "installer" / "backup_cleanup.sh"
    result = subprocess.run(
        ["bash", str(script)],
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "Backups dir: " + str(backup_dir) in result.stdout
    assert not older.exists()
    assert newest.exists()


def test_relative_runtime_paths_stay_at_the_stable_install_root(tmp_path, monkeypatch):
    install_dir = tmp_path / "opt/knx_to_openhab"
    release_dir = install_dir / "releases/v1.2.3-cafebabe"
    config_dir = tmp_path / "etc/knx_to_openhab"
    data_dir = tmp_path / "var/lib/knx_to_openhab"
    release_dir.mkdir(parents=True)
    config_dir.mkdir(parents=True)
    data_dir.mkdir(parents=True)
    (config_dir / "config.json").write_text(
        json.dumps(
            {
                "openhab_path": "openhab",
                "backups_dir": "var/backups/knx_to_openhab",
                "auth": {"enabled": False},
            }
        ),
        encoding="utf-8",
    )
    (config_dir / "secrets.env").write_text("", encoding="utf-8")
    (data_dir / "generator.json").write_text('{"general":{}}', encoding="utf-8")
    monkeypatch.setenv("KNXOH_INSTALL_DIR", str(install_dir))
    monkeypatch.setenv("KNXOH_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("KNXOH_DATA_DIR", str(data_dir))
    monkeypatch.setenv("KNXOH_BACKUP_DIR", str(tmp_path / "var/backups/knx_to_openhab"))
    monkeypatch.setenv("KNXOH_PATHS_FILE", str(tmp_path / "missing-paths.env"))

    config = load_config(release_dir)

    assert config["openhab_path"] == str(install_dir / "openhab")
    assert config["backups_dir"] == str(install_dir / "var/backups/knx_to_openhab")


def test_job_manager_relative_paths_stay_at_the_stable_install_root(tmp_path, monkeypatch):
    from web_ui.backend.jobs import JobManager

    install_dir = tmp_path / "opt/knx_to_openhab"
    release_dir = install_dir / "releases/v1.2.3-cafebabe"
    release_dir.mkdir(parents=True)
    monkeypatch.setenv("KNXOH_INSTALL_DIR", str(install_dir))
    monkeypatch.setenv("KNXOH_PATHS_FILE", str(tmp_path / "missing-paths.env"))

    manager = JobManager(
        {
            "jobs_dir": "var/lib/knx_to_openhab/jobs",
            "staging_dir": "var/lib/knx_to_openhab/staging",
            "backups_dir": "var/backups/knx_to_openhab",
        }
    )
    try:
        assert manager.jobs_dir == str(install_dir / "var/lib/knx_to_openhab/jobs")
        assert manager.staging_dir == str(install_dir / "var/lib/knx_to_openhab/staging")
        assert manager.backups_dir == str(install_dir / "var/backups/knx_to_openhab")
    finally:
        manager.executor.shutdown(wait=True)


@pytest.mark.parametrize("kind", ["directory", "file", "source_alias"])
def test_migration_rejects_symlinked_destinations_without_deleting_legacy(tmp_path, kind):
    paths = _fixture(tmp_path)
    old_jobs = paths[5]
    new_jobs = paths[3] / "jobs"
    new_jobs.parent.mkdir(parents=True, exist_ok=True)
    outside = tmp_path / "unrelated"
    outside.mkdir()
    sentinel = outside / "upload.knxproj"
    sentinel.write_text("unrelated data", encoding="utf-8")

    if kind == "directory":
        new_jobs.symlink_to(outside, target_is_directory=True)
    elif kind == "source_alias":
        new_jobs.symlink_to(old_jobs, target_is_directory=True)
    else:
        new_jobs.mkdir()
        (new_jobs / "upload.knxproj").symlink_to(sentinel)

    with pytest.raises(ValueError, match="symlink.*migration destination"):
        _run_migration(paths)

    assert sentinel.read_text(encoding="utf-8") == "unrelated data"
    assert (old_jobs / "upload.knxproj").read_text(encoding="utf-8") == "fixture upload"
    assert old_jobs.is_dir()
    assert not (paths[2].parent / "paths.env").exists()
