import base64
import json
import os
import subprocess
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


def _run_migration(paths):
    source_root, template_root, config_dir, data_dir, backup_dir, *_ = paths
    paths_file = config_dir.parent / "paths.env"
    return migrate_runtime_data(
        source_root,
        template_root,
        config_dir,
        data_dir,
        backup_dir,
        source_root,
        paths_file,
    )


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
