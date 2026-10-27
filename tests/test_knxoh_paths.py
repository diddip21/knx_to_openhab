import pytest

from installer.migrate_runtime_data import _write_paths_file
from knxoh_paths import get_paths
from web_ui.backend.storage import load_generator_config, save_generator_config


def _clear_path_environment(monkeypatch, tmp_path):
    for key in (
        "KNXOH_INSTALL_DIR",
        "KNXOH_CONFIG_DIR",
        "KNXOH_DATA_DIR",
        "KNXOH_BACKUP_DIR",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("KNXOH_PATHS_FILE", str(tmp_path / "missing-paths.env"))


def test_development_paths_keep_repository_layout(monkeypatch, tmp_path):
    _clear_path_environment(monkeypatch, tmp_path)

    paths = get_paths(tmp_path / "checkout")

    assert paths.project_root == (tmp_path / "checkout").resolve()
    assert paths.web_config_file == (tmp_path / "checkout/web_ui/backend/config.json").resolve()
    assert paths.generator_config_file == (tmp_path / "checkout/config.json").resolve()
    assert paths.jobs_dir == (tmp_path / "checkout/var/lib/knx_to_openhab").resolve()
    assert paths.backup_dir == (tmp_path / "checkout/var/backups/knx_to_openhab").resolve()
    assert paths.secrets_file is None


def test_release_code_resolves_shared_install_root_outside_version_directory(monkeypatch, tmp_path):
    _clear_path_environment(monkeypatch, tmp_path)
    install_dir = tmp_path / "opt/knx_to_openhab"
    release_dir = install_dir / "releases" / "1.2.3"
    release_dir.mkdir(parents=True)

    paths = get_paths(release_dir)

    assert paths.project_root == release_dir.resolve()
    assert paths.install_dir == install_dir.resolve()


def test_current_release_symlink_keeps_custom_user_paths_outside_release(monkeypatch, tmp_path):
    _clear_path_environment(monkeypatch, tmp_path)
    install_dir = tmp_path / "custom install"
    release_dir = install_dir / "releases" / "2.1.0"
    release_dir.mkdir(parents=True)
    current = install_dir / "current"
    try:
        current.symlink_to(release_dir, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("directory symlinks are unavailable")
    config_dir = tmp_path / "etc/knxoh"
    data_dir = tmp_path / "var/lib/knxoh"
    backup_dir = tmp_path / "var/backups/knxoh"
    monkeypatch.setenv("KNXOH_INSTALL_DIR", str(install_dir))
    monkeypatch.setenv("KNXOH_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("KNXOH_DATA_DIR", str(data_dir))
    monkeypatch.setenv("KNXOH_BACKUP_DIR", str(backup_dir))

    paths = get_paths(current)

    assert paths.project_root == release_dir.resolve()
    assert paths.install_dir == install_dir.resolve()
    assert paths.web_config_file == (config_dir / "config.json").resolve()
    assert paths.generator_config_file == (data_dir / "generator.json").resolve()
    assert paths.backup_dir == backup_dir.resolve()
    for user_path in (paths.web_config_file, paths.generator_config_file, paths.backup_dir):
        assert release_dir.resolve() not in user_path.parents


def test_installed_paths_use_external_config_and_data(monkeypatch, tmp_path):
    _clear_path_environment(monkeypatch, tmp_path)
    config_dir = tmp_path / "etc/knx_to_openhab"
    data_dir = tmp_path / "var/lib/knx_to_openhab"
    backup_dir = tmp_path / "var/backups/knx_to_openhab"
    monkeypatch.setenv("KNXOH_INSTALL_DIR", str(tmp_path / "opt/knx_to_openhab"))
    monkeypatch.setenv("KNXOH_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("KNXOH_DATA_DIR", str(data_dir))
    monkeypatch.setenv("KNXOH_BACKUP_DIR", str(backup_dir))

    paths = get_paths(tmp_path / "opt/knx_to_openhab/current")

    assert paths.install_dir == (tmp_path / "opt/knx_to_openhab").resolve()
    assert paths.web_config_file == (config_dir / "config.json").resolve()
    assert paths.generator_config_file == (data_dir / "generator.json").resolve()
    assert paths.secrets_file == (config_dir / "secrets.env").resolve()
    assert paths.jobs_dir == (data_dir / "jobs").resolve()
    assert paths.staging_dir == (data_dir / "staging").resolve()
    assert paths.generated_dir == (data_dir / "generated").resolve()
    assert paths.backup_dir == backup_dir.resolve()


def test_saved_environment_values_are_parsed_without_shell_execution(monkeypatch, tmp_path):
    path_file = tmp_path / "paths.env"
    install_dir = tmp_path / "app dir; touch SHOULD_NOT_EXIST"
    path_file.write_text(f'KNXOH_INSTALL_DIR="{install_dir}"\n', encoding="utf-8")
    _clear_path_environment(monkeypatch, tmp_path)
    monkeypatch.setenv("KNXOH_PATHS_FILE", str(path_file))

    paths = get_paths(tmp_path / "checkout")

    assert paths.install_dir == install_dir.resolve()
    assert not (tmp_path / "SHOULD_NOT_EXIST").exists()


def test_saved_paths_round_trip_dollar_quotes_and_backslashes(monkeypatch, tmp_path):
    custom_install = tmp_path / "app $cash 'quoted' \\path"
    path_file = tmp_path / "paths.env"
    _write_paths_file(path_file, {"KNXOH_INSTALL_DIR": custom_install})
    _clear_path_environment(monkeypatch, tmp_path)
    monkeypatch.setenv("KNXOH_PATHS_FILE", str(path_file))

    paths = get_paths(tmp_path / "checkout")

    assert paths.install_dir == custom_install.resolve()


def test_generator_config_reads_and_writes_external_file(monkeypatch, tmp_path):
    _clear_path_environment(monkeypatch, tmp_path)
    config_dir = tmp_path / "etc/knx_to_openhab"
    data_dir = tmp_path / "var/lib/knx_to_openhab"
    data_dir.mkdir(parents=True)
    generator_file = data_dir / "generator.json"
    generator_file.write_text('{"general": {"example": true}}\n', encoding="utf-8")
    monkeypatch.setenv("KNXOH_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("KNXOH_DATA_DIR", str(data_dir))

    loaded = load_generator_config(tmp_path / "checkout")
    loaded["general"]["other_setting"] = "kept"
    save_generator_config(loaded, tmp_path / "checkout")

    assert load_generator_config(tmp_path / "checkout") == {
        "general": {"example": True, "other_setting": "kept"}
    }
