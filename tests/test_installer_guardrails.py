import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("system_path", ["/etc", "/usr", "/var", "/home"])
def test_setup_rejects_system_wide_application_directory_before_writes(tmp_path, system_path):
    environment = os.environ.copy()
    environment.update(
        {
            "KNXOH_INSTALL_DIR": system_path,
            "KNXOH_CONFIG_DIR": str(tmp_path / "config"),
            "KNXOH_DATA_DIR": str(tmp_path / "data"),
            "KNXOH_BACKUP_DIR": str(tmp_path / "backups"),
        }
    )

    result = subprocess.run(
        ["bash", str(ROOT / "installer" / "setup.sh")],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    assert f"Refusing a system-wide path as application: {system_path}" in result.stderr


def test_setup_stops_service_before_migration_and_restarts_after_unit_reload():
    setup = (ROOT / "installer" / "setup.sh").read_text(encoding="utf-8")

    setup_start = setup.index('echo "Stopping services and waiting for the updater to finish"')
    stop_index = setup.index("quiesce_setup_services", setup_start)
    migration_index = setup.index("migrate_runtime_data.py")
    daemon_reload_index = setup.index("sudo systemctl daemon-reload", migration_index)
    restart_index = setup.index("setup_systemctl_if_unmasked knxohui.service restart")

    assert stop_index < migration_index < daemon_reload_index < restart_index
    assert "sudo systemctl enable --now knxohui.service" not in setup
    assert (
        'sudo install -o root -g root -m 0755 "$REPO_ROOT/installer/set_ui_password.py" ' in setup
    )
    assert "AUTH_PREFLIGHT_STATUS=3" in setup
    assert 'AUTH_PREFLIGHT_STATUS" -eq 1 || "$AUTH_PREFLIGHT_STATUS" -eq 3' in setup
    assert "generate one and show it once" in setup
    assert "Credential migration needs an interactive terminal" not in setup


def test_setup_rsync_does_not_overwrite_the_prepared_virtualenv():
    setup = (ROOT / "installer" / "setup.sh").read_text(encoding="utf-8")
    rsync_start = setup.index("sudo rsync -a")
    rsync_end = setup.index('\nif [[ ! -f "$BASE/config.json" ]]', rsync_start)

    assert "--exclude /venv" in setup[rsync_start:rsync_end]


def test_setup_can_recover_missing_credentials_without_a_tty(tmp_path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_sudo = fake_bin / "sudo"
    fake_sudo.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    fake_sudo.chmod(0o755)

    environment = os.environ.copy()
    environment.update(
        {
            "PATH": f"{fake_bin}:{environment['PATH']}",
            "KNXOH_INSTALL_DIR": str(tmp_path / "install"),
            "KNXOH_CONFIG_DIR": str(tmp_path / "config"),
            "KNXOH_DATA_DIR": str(tmp_path / "data"),
            "KNXOH_BACKUP_DIR": str(tmp_path / "backups"),
        }
    )

    result = subprocess.run(
        ["bash", str(ROOT / "installer" / "setup.sh")],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert "generate one and show it once" in result.stdout
    assert "If no usable Web UI password is configured" in result.stdout


def test_setup_uses_a_saved_custom_maintenance_lock_path(tmp_path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    sudo_log = tmp_path / "sudo.log"
    fake_sudo = fake_bin / "sudo"
    fake_sudo.write_text(
        '#!/usr/bin/env bash\nprintf "%s\\n" "$*" >> "$SETUP_SUDO_LOG"\nexit 1\n',
        encoding="utf-8",
    )
    fake_sudo.chmod(0o755)
    (fake_bin / "getent").write_text(
        '#!/usr/bin/env bash\n[[ "$1" == group && "$2" == knxohui ]]\n', encoding="utf-8"
    )
    (fake_bin / "getent").chmod(0o755)
    (fake_bin / "id").write_text(
        '#!/usr/bin/env bash\n[[ "$1" == -u && "$2" == knxohui ]] && echo 997\n',
        encoding="utf-8",
    )
    (fake_bin / "id").chmod(0o755)
    lock_file = tmp_path / "run locks" / "maintenance.lock"
    paths_file = tmp_path / "paths.env"
    paths_file.write_text(
        f'KNXOH_INSTALL_DIR="{tmp_path}/install"\n'
        f'KNXOH_CONFIG_DIR="{tmp_path}/config"\n'
        f'KNXOH_DATA_DIR="{tmp_path}/data"\n'
        f'KNXOH_BACKUP_DIR="{tmp_path}/backups"\n'
        f'KNXOH_MAINTENANCE_LOCK_FILE="{lock_file}"\n',
        encoding="utf-8",
    )
    environment = os.environ.copy()
    environment.update(
        {
            "PATH": f"{fake_bin}{os.pathsep}{environment['PATH']}",
            "SETUP_SUDO_LOG": str(sudo_log),
            "KNXOH_PATHS_FILE": str(paths_file),
        }
    )
    environment.pop("KNXOH_MAINTENANCE_LOCK_FILE", None)

    result = subprocess.run(
        ["bash", str(ROOT / "installer" / "setup.sh")],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )

    assert result.returncode != 0
    assert str(lock_file) in sudo_log.read_text(encoding="utf-8")
    assert "Credential migration needs an interactive terminal" not in result.stderr
    assert "No service, package or runtime data was changed" not in result.stderr


def test_setup_rejects_custom_lock_override_for_legacy_paths_file(tmp_path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    sudo_log = tmp_path / "sudo.log"
    fake_sudo = fake_bin / "sudo"
    fake_sudo.write_text(
        '#!/usr/bin/env bash\nprintf "%s\\n" "$*" >> "$SETUP_SUDO_LOG"\nexit 1\n',
        encoding="utf-8",
    )
    fake_sudo.chmod(0o755)
    paths_file = tmp_path / "paths.env"
    paths_file.write_text(
        f'KNXOH_INSTALL_DIR="{tmp_path}/install"\n'
        f'KNXOH_CONFIG_DIR="{tmp_path}/config"\n'
        f'KNXOH_DATA_DIR="{tmp_path}/data"\n'
        f'KNXOH_BACKUP_DIR="{tmp_path}/backups"\n',
        encoding="utf-8",
    )
    environment = os.environ.copy()
    environment.update(
        {
            "PATH": f"{fake_bin}{os.pathsep}{environment['PATH']}",
            "SETUP_SUDO_LOG": str(sudo_log),
            "KNXOH_PATHS_FILE": str(paths_file),
            "KNXOH_MAINTENANCE_LOCK_FILE": str(tmp_path / "custom.lock"),
        }
    )

    result = subprocess.run(
        ["bash", str(ROOT / "installer" / "setup.sh")],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )

    assert result.returncode == 2
    assert "legacy paths.env" in result.stderr
    assert not sudo_log.exists()


@pytest.mark.parametrize("location", ["shared-parent", "runtime-data"])
def test_setup_rejects_unsafe_maintenance_lock_parent_before_privileged_steps(tmp_path, location):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    sudo_log = tmp_path / "sudo.log"
    fake_sudo = fake_bin / "sudo"
    fake_sudo.write_text(
        '#!/usr/bin/env bash\nprintf "%s\\n" "$*" >> "$SETUP_SUDO_LOG"\nexit 1\n',
        encoding="utf-8",
    )
    fake_sudo.chmod(0o755)
    (fake_bin / "getent").write_text(
        '#!/usr/bin/env bash\n[[ "$1" == group && "$2" == knxohui ]]\n',
        encoding="utf-8",
    )
    (fake_bin / "getent").chmod(0o755)
    (fake_bin / "id").write_text(
        '#!/usr/bin/env bash\n[[ "$1" == -u && "$2" == knxohui ]] && echo 997\n',
        encoding="utf-8",
    )
    (fake_bin / "id").chmod(0o755)
    install_dir = tmp_path / "install"
    config_dir = tmp_path / "config"
    data_dir = tmp_path / "data"
    backup_dir = tmp_path / "backups"
    lock_file = (
        Path("/tmp/maintenance.lock")
        if location == "shared-parent"
        else data_dir / "maintenance.lock"
    )
    paths_file = tmp_path / "paths.env"
    paths_file.write_text(
        f'KNXOH_INSTALL_DIR="{install_dir}"\n'
        f'KNXOH_CONFIG_DIR="{config_dir}"\n'
        f'KNXOH_DATA_DIR="{data_dir}"\n'
        f'KNXOH_BACKUP_DIR="{backup_dir}"\n'
        f'KNXOH_MAINTENANCE_LOCK_FILE="{lock_file}"\n',
        encoding="utf-8",
    )
    environment = os.environ.copy()
    environment.update(
        {
            "PATH": f"{fake_bin}{os.pathsep}{environment['PATH']}",
            "SETUP_SUDO_LOG": str(sudo_log),
            "KNXOH_PATHS_FILE": str(paths_file),
        }
    )
    environment.pop("KNXOH_MAINTENANCE_LOCK_FILE", None)

    result = subprocess.run(
        ["bash", str(ROOT / "installer" / "setup.sh")],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )

    assert result.returncode == 2
    assert "dedicated" in result.stderr
    assert not sudo_log.exists()
