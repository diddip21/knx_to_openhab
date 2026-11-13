"""Host checks that must stop the installer before system changes."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

INSTALLER = Path(__file__).resolve().parents[1] / "install.sh"
pytestmark = pytest.mark.skipif(
    not sys.platform.startswith("linux") or shutil.which("bash") is None,
    reason="the installer preflight requires Linux and Bash",
)


def _executable(path, contents):
    path.write_text(contents, encoding="utf-8")
    path.chmod(0o755)


def _environment(tmp_path, *, python_version="3.11", free_kib=1048576):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _executable(
        fake_bin / "python3",
        "#!/bin/sh\n"
        'if [ "${1:-}" = "-c" ]; then printf "%s\\n" "$PREFLIGHT_PYTHON_VERSION"; exit 0; fi\n'
        'exec "$PREFLIGHT_REAL_PYTHON" "$@"\n',
    )
    _executable(
        fake_bin / "df",
        "#!/bin/sh\n"
        'printf "%s\\n" "$2" >> "$PREFLIGHT_DF_LOG"\n'
        "printf 'Filesystem 1024-blocks Used Available Capacity Mounted on\\n'\n"
        'printf "/dev/test 99999999 0 %s 0%% /\\n" "$PREFLIGHT_FREE_KIB"\n',
    )
    _executable(
        fake_bin / "sudo",
        "#!/bin/sh\n"
        'if [ "${1:-}" = "mktemp" ]; then\n'
        '    printf "%s\\n" "$3" > "$PREFLIGHT_PROBE_TEMPLATE_LOG"\n'
        "    shift\n"
        '    exec "$@"\n'
        "fi\n"
        'if [ "${1:-}" = "rm" ]; then shift; exec /bin/rm "$@"; fi\n'
        'printf "called\\n" >> "$PREFLIGHT_SUDO_LOG"\n'
        "exit 99\n",
    )
    environment = os.environ.copy()
    environment.update(
        {
            "ALLOW_ROOT": "1",
            "KNXOH_INSTALL_DIR": str(tmp_path / "not-created" / "install"),
            "KNXOH_CONFIG_DIR": str(tmp_path / "config"),
            "PATH": f"{fake_bin}{os.pathsep}{environment['PATH']}",
            "PREFLIGHT_PYTHON_VERSION": python_version,
            "PREFLIGHT_REAL_PYTHON": sys.executable,
            "PREFLIGHT_FREE_KIB": str(free_kib),
            "PREFLIGHT_DF_LOG": str(tmp_path / "df.log"),
            "PREFLIGHT_SUDO_LOG": str(tmp_path / "sudo.log"),
            "PREFLIGHT_PROBE_TEMPLATE_LOG": str(tmp_path / "probe-template.log"),
        }
    )
    return environment


@pytest.mark.parametrize("option", ["--help", "--cancel"])
def test_help_and_cancel_work_without_python(tmp_path, option):
    environment = _environment(tmp_path)
    (tmp_path / "bin" / "python3").unlink()
    _executable(tmp_path / "bin" / "cat", '#!/bin/sh\nexec /bin/cat "$@"\n')
    environment["PATH"] = str(tmp_path / "bin")

    result = subprocess.run(
        ["/bin/bash", str(INSTALLER), option],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert not (tmp_path / "sudo.log").exists()


def test_missing_python_has_explicit_error_before_path_resolution(tmp_path):
    environment = _environment(tmp_path)
    (tmp_path / "bin" / "python3").unlink()
    environment["PATH"] = str(tmp_path / "bin")
    environment.pop("KNXOH_INSTALL_DIR")
    environment.pop("KNXOH_CONFIG_DIR")

    result = subprocess.run(
        ["/bin/bash", str(INSTALLER), "--install"],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )

    assert result.returncode == 1
    assert "python3 was not found" in result.stdout + result.stderr
    assert not (tmp_path / "sudo.log").exists()


def test_unsupported_python_stops_before_sudo(tmp_path):
    environment = _environment(tmp_path, python_version="3.10")

    result = subprocess.run(
        ["bash", str(INSTALLER), "--install"],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )

    assert result.returncode == 1
    assert "Python 3.11 or newer is required" in result.stdout + result.stderr
    assert not (tmp_path / "sudo.log").exists()


def test_sudo_python_must_meet_installer_minimum(tmp_path):
    environment = _environment(tmp_path)
    environment["PREFLIGHT_SUDO_PYTHON_VERSION"] = "3.10"
    _executable(
        tmp_path / "bin" / "sudo",
        "#!/bin/sh\n"
        'if [ "${1:-}" = "python3" ]; then printf "%s\\n" "$PREFLIGHT_SUDO_PYTHON_VERSION"; exit 0; fi\n'
        'printf "called\\n" >> "$PREFLIGHT_SUDO_LOG"\n'
        "exit 99\n",
    )

    result = subprocess.run(
        ["bash", "-c", 'source "$1"; check_sudo_installer_python', "preflight", str(INSTALLER)],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )

    assert result.returncode == 1
    assert "must be available through sudo as python3" in result.stdout + result.stderr


def test_unsupported_python_is_rejected_before_reading_saved_paths(tmp_path):
    environment = _environment(tmp_path, python_version="3.10")
    environment.pop("KNXOH_INSTALL_DIR")
    environment.pop("KNXOH_CONFIG_DIR")
    paths_file = tmp_path / "paths.env"
    paths_file.write_text("KNXOH_INSTALL_DIR='unterminated\n", encoding="utf-8")
    environment["KNXOH_PATHS_FILE"] = str(paths_file)

    result = subprocess.run(
        ["bash", str(INSTALLER), "--install"],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )

    assert result.returncode == 1
    assert "Python 3.11 or newer is required" in result.stdout + result.stderr
    assert "No closing quotation" not in result.stderr
    assert not (tmp_path / "sudo.log").exists()


def test_installed_dependencies_do_not_refresh_package_lists(tmp_path):
    environment = _environment(tmp_path)
    dpkg_query = """#!/bin/sh
printf "installed\\n" >> "$PREFLIGHT_DPKG_LOG"
printf "installed\\n"
"""
    _executable(
        tmp_path / "bin" / "dpkg-query",
        dpkg_query,
    )

    result = subprocess.run(
        ["bash", "-c", 'source "$1"; install_dependencies', "preflight", str(INSTALLER)],
        env={**environment, "PREFLIGHT_DPKG_LOG": str(tmp_path / "dpkg.log")},
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert len((tmp_path / "dpkg.log").read_text(encoding="utf-8").splitlines()) == 6
    assert not (tmp_path / "sudo.log").exists()


def test_low_disk_space_stops_before_sudo_or_release_lookup(tmp_path):
    environment = _environment(tmp_path, free_kib=1048575)

    result = subprocess.run(
        ["bash", str(INSTALLER), "--install"],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )

    assert result.returncode == 1
    assert "At least 1 GiB of free space" in result.stdout + result.stderr
    assert (tmp_path / "df.log").read_text(encoding="utf-8").splitlines() == [str(tmp_path)]
    assert not (tmp_path / "sudo.log").exists()


def test_os_check_handles_missing_id_like(tmp_path):
    environment = _environment(tmp_path)
    os_release = tmp_path / "os-release"
    os_release.write_text('ID=example\nPRETTY_NAME="Example Linux"\n', encoding="utf-8")

    result = subprocess.run(
        [
            "/bin/bash",
            "-c",
            'source "$1"; check_os "$2"',
            "preflight",
            str(INSTALLER),
            str(os_release),
        ],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )

    assert "designed for Debian-based systems" in result.stdout + result.stderr
    assert "unbound variable" not in result.stderr


def test_venv_probe_fails_cleanly_before_setup(tmp_path):
    environment = _environment(tmp_path)
    different_tmp = tmp_path / "tmpdir"
    different_tmp.mkdir()
    environment["TMPDIR"] = str(different_tmp)
    _executable(tmp_path / "bin" / "python3", "#!/bin/sh\nexit 7\n")

    result = subprocess.run(
        ["bash", "-c", 'source "$1"; verify_venv_support', "preflight", str(INSTALLER)],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )

    assert result.returncode == 1
    assert "Could not create a temporary Python virtual environment" in result.stdout
    assert (tmp_path / "probe-template.log").read_text(encoding="utf-8").strip() == str(
        tmp_path / ".knxoh-preflight.XXXXXX"
    )
    assert list(tmp_path.glob(".knxoh-preflight.*")) == []
    assert list(different_tmp.iterdir()) == []


def test_venv_probe_accepts_usable_interpreter_and_cleans_up(tmp_path):
    environment = _environment(tmp_path)
    different_tmp = tmp_path / "tmpdir"
    different_tmp.mkdir()
    environment["TMPDIR"] = str(different_tmp)
    _executable(
        tmp_path / "bin" / "sudo",
        "#!/bin/sh\n"
        'if [ "${1:-}" = "mktemp" ]; then\n'
        '    printf "%s\\n" "$3" > "$PREFLIGHT_PROBE_TEMPLATE_LOG"\n'
        "    shift\n"
        '    exec "$@"\n'
        "fi\n"
        'if [ "${1:-}" = "python3" ]; then shift; exec "$PREFLIGHT_REAL_PYTHON" "$@"; fi\n'
        'if [ "${1:-}" = "-u" ]; then shift 2; fi\n'
        'if [ "${1:-}" = "rm" ]; then shift; exec /bin/rm "$@"; fi\n'
        'exec "$@"\n',
    )

    result = subprocess.run(
        ["bash", "-c", 'source "$1"; verify_venv_support', "preflight", str(INSTALLER)],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=40,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert (tmp_path / "probe-template.log").read_text(encoding="utf-8").strip() == str(
        tmp_path / ".knxoh-preflight.XXXXXX"
    )
    assert list(tmp_path.glob(".knxoh-preflight.*")) == []
    assert list(different_tmp.iterdir()) == []
