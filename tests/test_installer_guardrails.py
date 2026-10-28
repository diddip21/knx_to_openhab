import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _bash_script_copy(tmp_path, source: Path) -> Path:
    script = tmp_path / source.name
    script.write_text(source.read_text(encoding="utf-8"), encoding="utf-8", newline="\n")
    return script


@pytest.mark.parametrize("system_path", ["/etc", "/usr", "/var", "/home"])
@pytest.mark.skipif(os.name != "posix", reason="installer Bash requires POSIX")
def test_setup_rejects_system_wide_application_directory_before_writes(tmp_path, system_path):
    setup_script = _bash_script_copy(tmp_path, ROOT / "installer" / "setup.sh")
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
        ["bash", str(setup_script)],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    assert f"Refusing a system-wide path as application: {system_path}" in result.stderr


def test_setup_stops_service_before_migration_and_restarts_after_unit_reload():
    setup = (ROOT / "installer" / "setup.sh").read_text(encoding="utf-8")
    normal_setup = setup[setup.index('sudo touch "$STAGING_DIR/.install-incomplete"') :]

    stop_index = normal_setup.index("stop_unit_if_active knxohui.service")
    migration_index = normal_setup.index("migrate_runtime_data.py")
    daemon_reload_index = normal_setup.index("sudo systemctl daemon-reload")
    restart_index = normal_setup.index("sudo systemctl restart knxohui.service")

    assert stop_index < migration_index < daemon_reload_index < restart_index
    assert "sudo systemctl enable --now knxohui.service" not in normal_setup
    assert (
        'sudo install -o root -g root -m 0755 "$STAGING_DIR/installer/set_ui_password.py" ' in setup
    )


def test_setup_stages_release_and_switches_current_after_migration():
    setup = (ROOT / "installer" / "setup.sh").read_text(encoding="utf-8")
    normal_setup = setup[
        setup.index('transaction_state_temporary="$TRANSACTION_STATE_STAGING_FILE.tmp.$$"') :
    ]

    assert 'RELEASE_DIR="$BASE/releases/$RELEASE_VERSION"' in setup
    assert 'STAGING_DIR="$BASE/releases/.${RELEASE_VERSION}.staging.$$"' in setup
    assert 'sudo mv "$STAGING_DIR" "$RELEASE_DIR"' in setup
    assert 'sudo mv -Tf "$CURRENT_LINK_TMP" "$BASE/current"' in setup
    migration_index = normal_setup.index("migrate_runtime_data.py")
    publish_index = normal_setup.index('sudo mv -Tf "$CURRENT_LINK_TMP" "$BASE/current"')
    transaction_state_index = normal_setup.index('>"$transaction_state_temporary"')
    persist_state_index = normal_setup.index(
        'sudo mv -Tf "$transaction_state_temporary" "$TRANSACTION_STATE_STAGING_FILE"'
    )
    release_move_index = normal_setup.index('sudo mv "$STAGING_DIR" "$RELEASE_DIR"')
    stop_index = normal_setup.index("stop_unit_if_active knxohui-backup-cleanup.timer")
    restart_index = normal_setup.index("sudo systemctl restart knxohui.service")
    health_index = normal_setup.index("The Web UI service did not become healthy")
    cleanup_index = normal_setup.index("    --cleanup-legacy \\\n")
    assert publish_index < migration_index < restart_index < health_index < cleanup_index
    assert (
        transaction_state_index
        < persist_state_index
        < release_move_index
        < stop_index
        < publish_index
    )
    assert "--secure-snapshot-root" in normal_setup


def test_setup_keeps_application_releases_root_owned_and_not_service_writable():
    setup = (ROOT / "installer" / "setup.sh").read_text(encoding="utf-8")

    assert 'sudo chown root:root "$BASE" "$RELEASES_DIR"' in setup
    assert 'sudo chown -R root:root "$RELEASES_DIR"' in setup
    assert 'sudo chown -R root:root "$RELEASE_DIR"' in setup
    assert 'sudo chmod -R go-w "$RELEASE_DIR"' in setup
    assert 'sudo chown -R "$SERVICE_USER":"$SERVICE_USER" "$BASE"' not in setup


@pytest.mark.skipif(os.name != "posix", reason="launch scripts require POSIX process semantics")
def test_launchers_prefer_current_release_and_fall_back_to_legacy_flat_install(tmp_path):
    release_root = tmp_path / "release-install"
    version_dir = release_root / "releases" / "3.4.5"
    (version_dir / "venv/bin").mkdir(parents=True)
    (version_dir / "web_ui/backend").mkdir(parents=True)
    (version_dir / "installer").mkdir(parents=True)
    (version_dir / "web_ui/backend/gunicorn_conf.py").write_text("", encoding="utf-8")
    gunicorn = version_dir / "venv/bin/gunicorn"
    gunicorn.write_text("#!/bin/sh\npwd -P\n", encoding="utf-8")
    gunicorn.chmod(0o755)
    cleanup = version_dir / "installer/backup_cleanup.sh"
    cleanup.write_text("printf '%s' \"$0\"\n", encoding="utf-8")
    current = release_root / "current"
    try:
        current.symlink_to(version_dir, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("directory symlinks are unavailable")

    legacy_root = tmp_path / "legacy-install"
    (legacy_root / "venv/bin").mkdir(parents=True)
    (legacy_root / "web_ui/backend").mkdir(parents=True)
    (legacy_root / "installer").mkdir(parents=True)
    (legacy_root / "web_ui/backend/gunicorn_conf.py").write_text("", encoding="utf-8")
    legacy_gunicorn = legacy_root / "venv/bin/gunicorn"
    legacy_gunicorn.write_text("#!/bin/sh\npwd -P\n", encoding="utf-8")
    legacy_gunicorn.chmod(0o755)
    (legacy_root / "installer/backup_cleanup.sh").write_text(
        "printf '%s' \"$0\"\n", encoding="utf-8"
    )

    for install_dir, expected_dir, expected_cleanup in (
        (
            release_root,
            version_dir,
            release_root / "current/installer/backup_cleanup.sh",
        ),
        (
            legacy_root,
            legacy_root,
            legacy_root / "installer/backup_cleanup.sh",
        ),
    ):
        environment = os.environ.copy()
        environment["KNXOH_INSTALL_DIR"] = str(install_dir)
        for launcher, expected in (
            (ROOT / "installer/launch_web.sh", expected_dir),
            (ROOT / "installer/launch_backup_cleanup.sh", expected_cleanup),
        ):
            launcher_copy = _bash_script_copy(tmp_path, launcher)
            result = subprocess.run(
                ["bash", str(launcher_copy)],
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )
            assert result.returncode == 0, result.stderr
            assert result.stdout.rstrip("\n") == str(expected)
