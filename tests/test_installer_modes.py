import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "install.sh"


pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="Bash is required")


def run_installer(tmp_path, args, *, existing=False, git_checkout=False, setup_script=False):
    install_dir = tmp_path / "install"
    if existing:
        install_dir.mkdir(exist_ok=True)
    if git_checkout:
        (install_dir / ".git").mkdir()
    if setup_script:
        setup_path = install_dir / "installer" / "setup.sh"
        setup_path.parent.mkdir(parents=True, exist_ok=True)
        setup_path.write_text("#!/usr/bin/env bash\n", encoding="utf-8")

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    sudo_marker = tmp_path / "sudo-called"
    fake_sudo = fake_bin / "sudo"
    fake_sudo.write_text(
        '#!/bin/sh\nprintf called >> "$SUDO_MARKER"\nexit 97\n',
        encoding="utf-8",
    )
    fake_sudo.chmod(0o755)

    environment = os.environ.copy()
    environment.update(
        {
            "ALLOW_ROOT": "1",
            "KNXOH_INSTALL_DIR": str(install_dir),
            "KNXOH_CONFIG_DIR": str(tmp_path / "config"),
            "SUDO_MARKER": str(sudo_marker),
            "PATH": f"{fake_bin}{os.pathsep}{environment['PATH']}",
        }
    )
    result = subprocess.run(
        ["bash", str(INSTALLER), *args],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    return result, install_dir, sudo_marker


def test_installer_has_valid_bash_syntax():
    result = subprocess.run(
        ["bash", "-n", str(INSTALLER)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_fresh_install_defaults_to_install_mode_before_sudo(tmp_path):
    result, _, _ = run_installer(tmp_path, [])

    assert "Selected installer mode: install" in result.stdout


def test_help_returns_before_sudo(tmp_path):
    result, _, sudo_marker = run_installer(tmp_path, ["--help"])

    assert result.returncode == 0
    assert "--update" in result.stdout
    assert not sudo_marker.exists()


def test_unknown_option_returns_usage_error_before_sudo(tmp_path):
    result, _, sudo_marker = run_installer(tmp_path, ["--unknown"])

    assert result.returncode == 2
    assert "Unknown option: --unknown" in result.stderr
    assert not sudo_marker.exists()


def test_existing_installation_requires_explicit_mode_noninteractively(tmp_path):
    result, _, sudo_marker = run_installer(tmp_path, [], existing=True)

    assert result.returncode == 2
    assert "Choose --update, --repair or --cancel" in result.stderr
    assert not sudo_marker.exists()


def test_install_refuses_to_overwrite_existing_installation(tmp_path):
    result, install_dir, sudo_marker = run_installer(
        tmp_path, ["--install"], existing=True
    )

    assert result.returncode == 2
    assert "existing files were left untouched" in result.stderr
    assert install_dir.is_dir()
    assert not sudo_marker.exists()


def test_update_requires_existing_git_checkout(tmp_path):
    result, _, sudo_marker = run_installer(tmp_path, ["--update"], existing=True)

    assert result.returncode == 2
    assert "not a Git checkout" in result.stderr
    assert not sudo_marker.exists()


def test_update_requires_an_existing_installation(tmp_path):
    result, _, sudo_marker = run_installer(tmp_path, ["--update"])

    assert result.returncode == 2
    assert "No existing installation found" in result.stderr
    assert not sudo_marker.exists()


def test_repair_requires_existing_setup_script(tmp_path):
    result, _, sudo_marker = run_installer(tmp_path, ["--repair"], existing=True)

    assert result.returncode == 2
    assert "installer/setup.sh is missing" in result.stderr
    assert not sudo_marker.exists()


def test_repair_requires_an_existing_installation(tmp_path):
    result, _, sudo_marker = run_installer(tmp_path, ["--repair"])

    assert result.returncode == 2
    assert "No existing installation found" in result.stderr
    assert not sudo_marker.exists()


def test_cancel_leaves_existing_installation_untouched(tmp_path):
    install_dir = tmp_path / "install"
    install_dir.mkdir()
    sentinel = install_dir / "user-data.json"
    sentinel.write_text('{"preserve": true}', encoding="utf-8")

    result, _, sudo_marker = run_installer(tmp_path, ["--cancel"], existing=True)

    assert result.returncode == 0
    assert "no system or installation changes were made" in result.stdout
    assert not sudo_marker.exists()
    assert sentinel.read_text(encoding="utf-8") == '{"preserve": true}'
