import os
import shlex
import shutil
import stat
import subprocess
import sys
import tarfile
import time
from pathlib import Path

import pytest

from installer.create_update_backup import create_update_backup


def _make_snapshot_paths(tmp_path):
    install_dir = tmp_path / "opt/knx_to_openhab"
    config_dir = tmp_path / "etc/knx_to_openhab"
    data_dir = tmp_path / "var/lib/knx_to_openhab"
    backup_dir = tmp_path / "var/backups/knx_to_openhab"
    (install_dir / ".git").mkdir(parents=True)
    (install_dir / "venv/bin").mkdir(parents=True)
    (install_dir / "web_ui/backend").mkdir(parents=True)
    config_dir.mkdir(parents=True)
    data_dir.mkdir(parents=True)
    backup_dir.mkdir(parents=True)
    (install_dir / "app.py").write_text("application", encoding="utf-8")
    (install_dir / ".git/config").write_text("git metadata", encoding="utf-8")
    (install_dir / "venv/bin/python").write_text("virtual environment", encoding="utf-8")
    (install_dir / "web_ui/backend/__pycache__").mkdir()
    (install_dir / "web_ui/backend/__pycache__/app.pyc").write_bytes(b"bytecode")
    (config_dir / "config.json").write_text('{"port": 8085}', encoding="utf-8")
    (config_dir / "secrets.env").write_text("KNXOH_UI_PASSWORD_HASH_B64=secret", encoding="utf-8")
    generator_config = data_dir / "generator.json"
    generator_config.write_text('{"general": {}}', encoding="utf-8")
    (data_dir / "jobs").mkdir()
    (data_dir / "jobs/job.json").write_text('{"status": "complete"}', encoding="utf-8")
    return install_dir, config_dir, generator_config, backup_dir


def test_update_backup_contains_application_configuration_and_runtime_data(tmp_path):
    install_dir, config_dir, generator_config, backup_dir = _make_snapshot_paths(tmp_path)
    data_dir = tmp_path / "var/lib/knx_to_openhab"

    backup_path = create_update_backup(
        install_dir, config_dir, data_dir, generator_config, backup_dir
    )

    assert backup_path.parent == backup_dir
    assert stat.S_IMODE(backup_path.stat().st_mode) == 0o600
    with tarfile.open(backup_path, mode="r:gz") as archive:
        members = {member.name for member in archive.getmembers()}
    assert "application/app.py" in members
    assert "configuration/config.json" in members
    assert "configuration/secrets.env" in members
    assert "runtime data/generator.json" in members
    assert "runtime data/jobs/job.json" in members
    assert not any("/.git/" in f"/{name}/" for name in members)
    assert not any("/venv/" in f"/{name}/" for name in members)
    assert not any("__pycache__" in name or name.endswith(".pyc") for name in members)


def test_update_backup_is_not_published_when_archive_validation_fails(monkeypatch, tmp_path):
    install_dir, config_dir, generator_config, backup_dir = _make_snapshot_paths(tmp_path)

    def reject_archive(*_args):
        raise tarfile.ReadError("simulated archive corruption")

    monkeypatch.setattr("installer.create_update_backup._verify_archive", reject_archive)

    with pytest.raises(tarfile.ReadError, match="simulated archive corruption"):
        create_update_backup(
            install_dir,
            config_dir,
            tmp_path / "var/lib/knx_to_openhab",
            generator_config,
            backup_dir,
        )

    assert list(backup_dir.iterdir()) == []


def test_update_backup_refuses_to_write_inside_the_application_tree(tmp_path):
    install_dir, config_dir, generator_config, _ = _make_snapshot_paths(tmp_path)

    with pytest.raises(ValueError, match="outside the application directory"):
        create_update_backup(
            install_dir,
            config_dir,
            tmp_path / "var/lib/knx_to_openhab",
            generator_config,
            install_dir / "backups",
        )


pytestmark = pytest.mark.skipif(
    os.name != "posix" or shutil.which("bash") is None or shutil.which("flock") is None,
    reason="The update script lifecycle tests require Linux utilities",
)


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def _make_update_fixture(tmp_path, *, backup_path=None, git_status="", hold_fetch=False):
    root = Path(__file__).resolve().parents[1]
    install_dir = tmp_path / "install"
    config_dir = tmp_path / "config"
    data_dir = tmp_path / "data"
    backup_dir = backup_path or tmp_path / "backups"
    fake_bin = tmp_path / "bin"
    (install_dir / "installer").mkdir(parents=True)
    (install_dir / "web_ui/backend").mkdir(parents=True)
    (install_dir / "venv/bin").mkdir(parents=True)
    (install_dir / ".git").mkdir()
    config_dir.mkdir()
    data_dir.mkdir()
    fake_bin.mkdir()
    shutil.copy2(root / "update.sh", install_dir / "update.sh")
    shutil.copy2(root / "knxoh_paths.py", install_dir / "knxoh_paths.py")
    shutil.copy2(
        root / "installer/create_update_backup.py",
        install_dir / "installer/create_update_backup.py",
    )
    shutil.copy2(root / "web_ui/backend/auth.py", install_dir / "web_ui/backend/auth.py")
    (install_dir / "config.json").write_text('{"general": {"legacy": true}}', encoding="utf-8")
    (install_dir / "web_ui/backend/config.json").write_text(
        '{"auth": {"enabled": false}}', encoding="utf-8"
    )
    (data_dir / "generator.json").write_text('{"general": {}}', encoding="utf-8")
    (config_dir / "config.json").write_text('{"auth": {"enabled": false}}', encoding="utf-8")
    (config_dir / "secrets.env").write_text("", encoding="utf-8")
    (config_dir / "paths.env").write_text("KNXOH_CONFIG_DIR=test\n", encoding="utf-8")
    real_python = sys.executable
    (install_dir / "venv/bin/python").write_text(
        f'#!/bin/sh\nexec {shlex.quote(real_python)} "$@"\n',
        encoding="utf-8",
    )
    (install_dir / "venv/bin/python").chmod(0o755)
    git_log = tmp_path / "git.log"
    fetch_marker = tmp_path / "fetch.started"
    git_script = [
        "#!/bin/sh",
        'printf "%s\n" "$*" >> "$GIT_LOG"',
        'case "$*" in',
        '  *"rev-parse --git-dir"*) printf ".git\n"; exit 0 ;;',
        '  *"status --porcelain"*)',
        '    if [ "$FAKE_GIT_STATUS" = "legacy-config" ]; then',
        '      case "$*" in',
        '        *":(exclude,top)config.json"*"web_ui/backend/config.json"*) exit 0 ;;',
        "      esac",
        "    fi",
        '    printf "%s" "$FAKE_GIT_STATUS"; exit 0 ;;',
        '  *"fetch --depth 1 origin"*)',
        '    touch "$FETCH_MARKER"',
        '    if [ "$HOLD_FETCH" = "1" ]; then sleep 3; fi',
        "    exit 1 ;;",
        "  *) exit 90 ;;",
        "esac",
    ]
    _write_executable(fake_bin / "git", "\n".join(git_script) + "\n")
    sudo_script = [
        "#!/bin/sh",
        'if [ "$1" = "-n" ] && [ "$2" = "-l" ]; then',
        "  printf '%s\n' 'User knxohui may run the following commands:'",
        "  printf '%s\n' '    (root) NOPASSWD: /bin/systemctl restart knxohui.service'",
        "  exit 0",
        "fi",
        "exit 0",
    ]
    _write_executable(fake_bin / "sudo", "\n".join(sudo_script) + "\n")
    environment = os.environ.copy()
    environment.update(
        {
            "INSTALL_DIR": str(install_dir),
            "KNXOH_INSTALL_DIR": str(install_dir),
            "KNXOH_CONFIG_DIR": str(config_dir),
            "KNXOH_DATA_DIR": str(data_dir),
            "KNXOH_BACKUP_DIR": str(backup_dir),
            "KNXOH_PATHS_FILE": str(config_dir / "paths.env"),
            "RELEASE_TAG": "v1.2.3",
            "LOG_FILE": str(tmp_path / "update.log"),
            "GIT_LOG": str(git_log),
            "FETCH_MARKER": str(fetch_marker),
            "FAKE_GIT_STATUS": git_status,
            "HOLD_FETCH": "1" if hold_fetch else "0",
            "PATH": f"{fake_bin}{os.pathsep}{environment['PATH']}",
        }
    )
    return install_dir, environment, git_log, fetch_marker, data_dir, backup_dir


def test_update_stops_before_fetch_when_snapshot_creation_fails(tmp_path):
    blocker = tmp_path / "backup-is-a-file"
    blocker.write_text("not a directory", encoding="utf-8")
    install_dir, environment, git_log, _, _, _ = _make_update_fixture(tmp_path, backup_path=blocker)

    result = subprocess.run(
        ["bash", str(install_dir / "update.sh")],
        env=environment,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )

    assert result.returncode == 1
    assert "Could not create and validate the pre-update backup" in result.stdout
    commands = git_log.read_text(encoding="utf-8")
    assert "status --porcelain" in commands
    assert "fetch --depth 1" not in commands
    assert "stash" not in commands


def test_update_refuses_local_changes_before_creating_a_backup(tmp_path):
    install_dir, environment, git_log, _, data_dir, backup_dir = _make_update_fixture(
        tmp_path, git_status=" M local.py\n"
    )

    result = subprocess.run(
        ["bash", str(install_dir / "update.sh")],
        env=environment,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )

    assert result.returncode == 1
    assert "Local application changes are present" in result.stdout
    assert "fetch --depth 1" not in git_log.read_text(encoding="utf-8")
    assert not backup_dir.exists()
    assert (data_dir / "updater.lock").is_file()


def test_update_allows_preserved_legacy_configs_after_external_config_validation(tmp_path):
    install_dir, environment, git_log, _, _, _ = _make_update_fixture(
        tmp_path, git_status="legacy-config"
    )

    result = subprocess.run(
        ["bash", str(install_dir / "update.sh")],
        env=environment,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )

    assert result.returncode == 1
    assert "Local application changes are present" not in result.stdout
    assert "Fetching selected stable release" in result.stdout
    assert "fetch --depth 1" in git_log.read_text(encoding="utf-8")


def test_only_one_update_can_hold_the_runtime_lock(tmp_path):
    install_dir, environment, git_log, fetch_marker, _, _ = _make_update_fixture(
        tmp_path, hold_fetch=True
    )
    first = subprocess.Popen(
        ["bash", str(install_dir / "update.sh")],
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline and not fetch_marker.exists():
            if first.poll() is not None:
                break
            time.sleep(0.05)
        assert fetch_marker.exists(), "first update did not reach the fetch step"

        second = subprocess.run(
            ["bash", str(install_dir / "update.sh")],
            env=environment,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        assert second.returncode == 1
        assert "Another KNX to openHAB update is already running" in second.stdout
    finally:
        first_output, _ = first.communicate(timeout=10)

    assert first.returncode == 1, first_output
    assert git_log.read_text(encoding="utf-8").count("fetch --depth 1") == 1
