import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "install.sh"
KIB_FLOOR = 1024 * 1024

pytestmark = pytest.mark.skipif(
    os.name != "posix" or shutil.which("bash") is None,
    reason="installer shell integration tests require a POSIX Bash environment",
)


def make_preflight_environment(
    tmp_path, *, free_kib=KIB_FLOOR, python_version="3.11", curl_status=0
):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    df = fake_bin / "df"
    df.write_text(
        '#!/bin/sh\nprintf \'%s\\n\' "$2" >> "$PREFLIGHT_DF_PATH_LOG"\n'
        "printf 'Filesystem 1024-blocks Used Available Capacity Mounted on\\n'\n"
        "printf '/dev/test 99999999 0 %s 0%% /\\n' \"$PREFLIGHT_FREE_KIB\"\n",
        encoding="utf-8",
    )
    df.chmod(0o755)
    python = fake_bin / "python3"
    python.write_text(
        "#!/bin/sh\n"
        "if [ \"$1\" = '-c' ]; then printf '%s\\n' \"$PREFLIGHT_PYTHON_VERSION\"; exit 0; fi\n"
        "if [ \"$1\" = '-m' ] && [ \"$2\" = 'venv' ]; then\n"
        '  if [ "$PREFLIGHT_VENV_STATUS" != 0 ]; then exit "$PREFLIGHT_VENV_STATUS"; fi\n'
        '  "$PREFLIGHT_REAL_PYTHON" "$@"\n'
        "  result=$?\n"
        '  if [ "$result" = 0 ] && [ "$PREFLIGHT_VENV_BROKEN_EXEC" = 1 ]; then\n'
        '    rm -f "$3/bin/python"\n'
        "    printf '#!/bin/sh\\nexit 1\\n' > \"$3/bin/python\"\n"
        '    /bin/chmod +x "$3/bin/python"\n'
        "  fi\n"
        '  exit "$result"\n'
        "fi\n"
        'exec "$PREFLIGHT_REAL_PYTHON" "$@"\n',
        encoding="utf-8",
    )
    python.chmod(0o755)
    curl = fake_bin / "curl"
    curl.write_text(
        '#!/bin/sh\nprintf called >> "$PREFLIGHT_CURL_LOG"\n' 'exit "$PREFLIGHT_CURL_STATUS"\n',
        encoding="utf-8",
    )
    curl.chmod(0o755)

    environment = os.environ.copy()
    environment.update(
        {
            "PATH": str(fake_bin),
            "KNXOH_INSTALL_DIR": str(tmp_path / "install"),
            "KNXOH_CONFIG_DIR": str(tmp_path / "config"),
            "PREFLIGHT_DF_PATH_LOG": str(tmp_path / "df-paths"),
            "PREFLIGHT_FREE_KIB": str(free_kib),
            "PREFLIGHT_PYTHON_VERSION": python_version,
            "PREFLIGHT_REAL_PYTHON": sys.executable,
            "PREFLIGHT_VENV_STATUS": "0",
            "PREFLIGHT_VENV_BROKEN_EXEC": "0",
            "PREFLIGHT_CURL_LOG": str(tmp_path / "curl-calls"),
            "PREFLIGHT_CURL_STATUS": str(curl_status),
        }
    )
    return environment, tmp_path


def run_preflight(environment, mode, install_dir):
    return subprocess.run(
        [
            "/bin/bash",
            "-c",
            'source "$1" && run_installer_preflight "$2" "$3"',
            "preflight-test",
            str(INSTALLER),
            mode,
            str(install_dir),
        ],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )


def run_venv_check(environment):
    return subprocess.run(
        [
            "/bin/bash",
            "-c",
            'source "$1" && verify_venv_support python3',
            "venv-test",
            str(INSTALLER),
        ],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )


def test_preflight_accepts_supported_host_python_disk_and_release_network(tmp_path):
    environment, root = make_preflight_environment(tmp_path)

    result = run_preflight(environment, "install", root / "install")

    assert result.returncode == 0, result.stderr
    assert (root / "curl-calls").read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("python_version", "expected_message"),
    [
        (None, "Python 3.11 or newer is required"),
        ("3.10", "Python 3.11 or newer is required"),
    ],
)
def test_preflight_rejects_missing_or_too_old_python_before_network(
    tmp_path, python_version, expected_message
):
    environment, root = make_preflight_environment(
        tmp_path, python_version=python_version or "3.10"
    )
    if python_version is None:
        (root / "bin" / "python3").unlink()

    result = run_preflight(environment, "install", root / "install")

    assert result.returncode != 0
    assert expected_message in result.stdout + result.stderr
    assert not (root / "curl-calls").exists()


@pytest.mark.parametrize("free_kib", [KIB_FLOOR - 1, KIB_FLOOR])
def test_preflight_enforces_documented_disk_floor_on_existing_parent(tmp_path, free_kib):
    environment, root = make_preflight_environment(tmp_path, free_kib=free_kib)
    install_dir = root / "not-created" / "yet" / "install"

    result = run_preflight(environment, "install", install_dir)

    if free_kib < KIB_FLOOR:
        assert result.returncode != 0
        assert "At least 1 GiB of free space" in result.stdout + result.stderr
        assert not (root / "curl-calls").exists()
    else:
        assert result.returncode == 0, result.stderr
        checked_path = Path((root / "df-paths").read_text(encoding="utf-8").splitlines()[0])
        assert checked_path == root


def test_preflight_reports_unreachable_github_before_package_changes(tmp_path):
    environment, root = make_preflight_environment(tmp_path, curl_status=28)

    result = run_preflight(environment, "update", root / "install")

    assert result.returncode != 0
    assert "Could not reach GitHub" in result.stdout + result.stderr
    assert (root / "curl-calls").is_file()


def test_repair_preflight_does_not_probe_release_network(tmp_path):
    environment, root = make_preflight_environment(tmp_path)

    result = run_preflight(environment, "repair", root / "install")

    assert result.returncode == 0, result.stderr
    assert not (root / "curl-calls").exists()


def test_failed_preflight_stops_before_apt_dependency_installation(tmp_path):
    environment, root = make_preflight_environment(tmp_path, free_kib=KIB_FLOOR - 1)
    install_dir = root / "existing-install"
    (install_dir / "installer").mkdir(parents=True)
    (install_dir / "installer" / "setup.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    sudo = root / "bin" / "sudo"
    sudo.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    sudo.chmod(0o755)
    apt_log = root / "apt-called"
    apt_get = root / "bin" / "apt-get"
    apt_get.write_text(
        '#!/bin/sh\nprintf called >> "$PREFLIGHT_APT_LOG"\nexit 0\n',
        encoding="utf-8",
    )
    apt_get.chmod(0o755)
    environment.update(
        {
            "ALLOW_ROOT": "1",
            "KNXOH_INSTALL_DIR": str(install_dir),
            "PREFLIGHT_APT_LOG": str(apt_log),
            "PATH": f"{root / 'bin'}:/usr/bin:/bin",
        }
    )

    result = subprocess.run(
        ["/bin/bash", str(INSTALLER), "--repair"],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )

    assert result.returncode != 0
    assert "At least 1 GiB of free space" in result.stdout + result.stderr
    assert not apt_log.exists()


def test_missing_python_is_reported_before_path_configuration_uses_python(tmp_path):
    environment, root = make_preflight_environment(tmp_path)
    (root / "bin" / "python3").unlink()
    environment.pop("KNXOH_INSTALL_DIR")
    environment.pop("KNXOH_CONFIG_DIR")

    result = subprocess.run(
        ["/bin/bash", str(INSTALLER), "--repair"],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )

    assert result.returncode != 0
    assert "Python 3.11 or newer is required" in result.stdout + result.stderr


@pytest.mark.parametrize("arguments", [["--help"], ["--cancel"]])
def test_help_and_cancel_work_without_python_or_path_overrides(tmp_path, arguments):
    environment, root = make_preflight_environment(tmp_path)
    (root / "bin" / "python3").unlink()
    environment.pop("KNXOH_INSTALL_DIR")
    environment.pop("KNXOH_CONFIG_DIR")
    cat = root / "bin" / "cat"
    cat.write_text('#!/bin/sh\nexec /bin/cat "$@"\n', encoding="utf-8")
    cat.chmod(0o755)

    result = subprocess.run(
        ["/bin/bash", str(INSTALLER), *arguments],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Python 3.11 or newer is required" not in result.stdout + result.stderr
    assert not (root / "curl-calls").exists()


def test_unsupported_python_is_rejected_before_release_resolution(tmp_path):
    environment, root = make_preflight_environment(tmp_path, python_version="3.10")
    environment["ALLOW_ROOT"] = "1"
    sudo = root / "bin" / "sudo"
    sudo.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    sudo.chmod(0o755)

    result = subprocess.run(
        ["/bin/bash", str(INSTALLER), "--install"],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )

    assert result.returncode != 0
    assert "Python 3.11 or newer is required" in result.stdout + result.stderr
    assert not (root / "curl-calls").exists()


def test_installer_runs_bounded_connectivity_probe_before_release_lookup(tmp_path):
    environment, root = make_preflight_environment(tmp_path, curl_status=28)
    environment.update(
        {
            "ALLOW_ROOT": "1",
            "PATH": f"{root / 'bin'}:/usr/bin:/bin",
        }
    )
    sudo = root / "bin" / "sudo"
    sudo.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    sudo.chmod(0o755)

    result = subprocess.run(
        ["/bin/bash", str(INSTALLER), "--install"],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )

    output = result.stdout + result.stderr
    assert result.returncode != 0
    assert "Could not reach GitHub" in output
    assert "Could not retrieve the latest stable GitHub release" not in output
    assert (root / "curl-calls").read_text(encoding="utf-8").count("called") == 1


def test_os_preflight_handles_missing_id_like_without_unbound_variable(tmp_path):
    environment, root = make_preflight_environment(tmp_path)
    os_release = root / "unsupported-os-release"
    os_release.write_text('ID=example\nPRETTY_NAME="Example Linux"\n', encoding="utf-8")

    result = subprocess.run(
        [
            "/bin/bash",
            "-c",
            'source "$1"; check_os "$2"',
            "os-check-test",
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


def test_venv_preflight_creates_and_removes_temporary_environment(tmp_path):
    environment, root = make_preflight_environment(tmp_path)
    environment.update({"PATH": f"{root / 'bin'}:/usr/bin:/bin", "TMPDIR": str(root)})

    result = run_venv_check(environment)

    assert result.returncode == 0, result.stdout + result.stderr
    assert list(root.glob("knxoh-preflight.*")) == []


def test_venv_preflight_reports_creation_failure_and_cleans_up(tmp_path):
    environment, root = make_preflight_environment(tmp_path)
    environment.update(
        {
            "PATH": f"{root / 'bin'}:/usr/bin:/bin",
            "TMPDIR": str(root),
            "PREFLIGHT_VENV_STATUS": "7",
        }
    )

    result = run_venv_check(environment)

    assert result.returncode != 0
    assert (
        "Could not create a temporary Python virtual environment" in result.stdout + result.stderr
    )
    assert list(root.glob("knxoh-preflight.*")) == []


def test_venv_preflight_reports_unusable_interpreter_and_cleans_up(tmp_path):
    environment, root = make_preflight_environment(tmp_path)
    environment.update(
        {
            "PATH": f"{root / 'bin'}:/usr/bin:/bin",
            "TMPDIR": str(root),
            "PREFLIGHT_VENV_BROKEN_EXEC": "1",
        }
    )

    result = run_venv_check(environment)

    assert result.returncode != 0
    assert "The temporary Python virtual environment is not usable" in result.stdout + result.stderr
    assert list(root.glob("knxoh-preflight.*")) == []


def test_installer_checks_venv_after_packages_but_before_setup(tmp_path):
    environment, root = make_preflight_environment(tmp_path)
    install_dir = root / "existing-install"
    installer_dir = install_dir / "installer"
    installer_dir.mkdir(parents=True)
    setup_marker = root / "setup-ran"
    (installer_dir / "setup.sh").write_text(
        f"#!/bin/sh\nprintf called > '{setup_marker}'\n", encoding="utf-8"
    )
    (installer_dir / "backup_cleanup.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    sudo = root / "bin" / "sudo"
    sudo.write_text(
        "#!/bin/sh\n"
        "if [ \"$1\" = '-n' ]; then exit 0; fi\n"
        'if [ "$1" = \'apt-get\' ]; then shift; exec apt-get "$@"; fi\n'
        "exit 0\n",
        encoding="utf-8",
    )
    sudo.chmod(0o755)
    apt_log = root / "apt-called"
    apt_get = root / "bin" / "apt-get"
    apt_get.write_text(
        '#!/bin/sh\nprintf called >> "$PREFLIGHT_APT_LOG"\nexit 0\n',
        encoding="utf-8",
    )
    apt_get.chmod(0o755)
    environment.update(
        {
            "ALLOW_ROOT": "1",
            "KNXOH_INSTALL_DIR": str(install_dir),
            "PREFLIGHT_APT_LOG": str(apt_log),
            "PREFLIGHT_VENV_STATUS": "7",
            "TMPDIR": str(root),
            "PATH": f"{root / 'bin'}:/usr/bin:/bin",
        }
    )

    result = subprocess.run(
        ["/bin/bash", str(INSTALLER), "--repair"],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
    )

    assert result.returncode != 0
    assert apt_log.is_file()
    assert (
        "Could not create a temporary Python virtual environment" in result.stdout + result.stderr
    )
    assert not setup_marker.exists()
    assert list(root.glob("knxoh-preflight.*")) == []
