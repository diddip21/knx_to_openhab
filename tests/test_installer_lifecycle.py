"""Isolated lifecycle coverage for the top-level Linux installer."""

import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "install.sh"


def _is_debian_based_linux() -> bool:
    if not sys.platform.startswith("linux") or shutil.which("bash") is None:
        return False
    try:
        os_release = Path("/etc/os-release").read_text(encoding="utf-8")
    except OSError:
        return False

    release_values = {}
    for line in os_release.splitlines():
        key, separator, value = line.partition("=")
        if separator:
            release_values[key] = value.strip().strip('"').strip("'")
    release_ids = {release_values.get("ID", ""), *release_values.get("ID_LIKE", "").split()}
    return "debian" in release_ids


pytestmark = pytest.mark.skipif(
    not _is_debian_based_linux(),
    reason="the installer lifecycle harness requires Debian-based Linux utilities",
)


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def test_clean_install_repeat_install_and_repair_are_isolated(tmp_path):
    install_dir = tmp_path / "install"
    config_dir = tmp_path / "config"
    data_dir = tmp_path / "data"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    setup_log = tmp_path / "setup.log"
    curl_log = tmp_path / "curl.log"
    clone_log = tmp_path / "clone.log"
    privileged_log = tmp_path / "privileged.log"

    _write_executable(
        fake_bin / "curl",
        "#!/bin/bash\n"
        'printf "%s\\n" "$*" >> "$CURL_LOG"\n'
        "cat <<'JSON'\n"
        '{"tag_name":"v1.2.3","draft":false,"prerelease":false}\n'
        "JSON\n",
    )
    _write_executable(
        fake_bin / "git",
        "#!/bin/bash\n"
        'if [[ "$1" != "clone" ]]; then exit 91; fi\n'
        'printf "%s\\n" "$*" >> "$CLONE_LOG"\n'
        'target="${@: -1}"\n'
        'mkdir -p "$target/.git" "$target/installer"\n'
        "cat > \"$target/installer/setup.sh\" <<'SETUP'\n"
        "#!/bin/bash\n"
        "set -euo pipefail\n"
        'printf "setup\\n" >> "$SETUP_LOG"\n'
        'mkdir -p "$KNXOH_DATA_DIR"\n'
        'if [[ ! -e "$KNXOH_DATA_DIR/user-data.json" ]]; then\n'
        '  printf \'{"created":true}\\n\' > "$KNXOH_DATA_DIR/user-data.json"\n'
        "fi\n"
        "SETUP\n"
        "cat > \"$target/installer/backup_cleanup.sh\" <<'CLEANUP'\n"
        "#!/bin/bash\nexit 0\n"
        "CLEANUP\n"
        "cat > \"$target/installer/web_ui_endpoint.py\" <<'ENDPOINT'\n"
        "# endpoint helper is handled by the isolated python shim\n"
        "ENDPOINT\n",
    )
    _write_executable(
        fake_bin / "sudo",
        "#!/bin/bash\n"
        'if [[ "$1" == "-n" && "$2" == "true" ]]; then exit 0; fi\n'
        'if [[ "$1" == "-n" ]]; then shift; fi\n'
        'if [[ "$1" == "apt-get" ]]; then printf "apt-get\\n" >> "$PRIVILEGED_LOG"; exit 0; fi\n'
        'exec "$@"\n',
    )
    _write_executable(
        fake_bin / "rsync",
        "#!/bin/bash\n"
        'source="${@: -2:1}"\n'
        'destination="${@: -1}"\n'
        'mkdir -p "$destination"\n'
        'cp -a "$source"/. "$destination"/\n',
    )
    _write_executable(
        fake_bin / "chmod",
        "#!/bin/bash\n"
        'if [[ "${FAKE_CHMOD_DENY:-0}" == 1 ]]; then exit 1; fi\n'
        'exec /bin/chmod "$@"\n',
    )
    _write_executable(
        fake_bin / "dpkg",
        "#!/bin/bash\n"
        "for package in git python3 python3-venv python3-pip rsync curl; do\n"
        '  printf "ii  %s 1.0 all installed\\n" "$package"\n'
        "done\n",
    )
    _write_executable(fake_bin / "hostname", "#!/bin/sh\nprintf '127.0.0.1\\n'\n")
    _write_executable(
        fake_bin / "python3",
        "#!/bin/bash\n"
        'for argument in "$@"; do\n'
        '  if [[ "$argument" == *"web_ui_endpoint.py" ]]; then\n'
        "    printf 'loopback\\n127.0.0.1\\n8085\\n'\n"
        "    exit 0\n"
        "  fi\n"
        "done\n"
        f'exec {shlex.quote(sys.executable)} "$@"\n',
    )

    environment = os.environ.copy()
    environment.update(
        {
            "ALLOW_ROOT": "1",
            "KNXOH_INSTALL_DIR": str(install_dir),
            "KNXOH_CONFIG_DIR": str(config_dir),
            "KNXOH_DATA_DIR": str(data_dir),
            "SETUP_LOG": str(setup_log),
            "PRIVILEGED_LOG": str(privileged_log),
            "CURL_LOG": str(curl_log),
            "CLONE_LOG": str(clone_log),
            "PATH": str(fake_bin) + os.pathsep + environment["PATH"],
        }
    )

    def run_installer(*arguments):
        return subprocess.run(
            ["bash", str(INSTALLER), *arguments],
            env=environment,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )

    fresh_install = run_installer("--install")
    assert fresh_install.returncode == 0, fresh_install.stdout + fresh_install.stderr
    assert "Cloning release v1.2.3" in fresh_install.stdout
    assert setup_log.read_text(encoding="utf-8").splitlines() == ["setup"]
    assert len(curl_log.read_text(encoding="utf-8").splitlines()) == 1
    assert "--branch v1.2.3" in clone_log.read_text(encoding="utf-8")

    user_data = data_dir / "user-data.json"
    user_data.write_text(json.dumps({"created": True, "custom": "keep"}), encoding="utf-8")
    second_install = run_installer("--install")
    assert second_install.returncode == 2
    assert "existing files were left untouched" in second_install.stdout
    assert user_data.read_text(encoding="utf-8") == '{"created": true, "custom": "keep"}'
    assert setup_log.read_text(encoding="utf-8").splitlines() == ["setup"]
    assert len(curl_log.read_text(encoding="utf-8").splitlines()) == 1

    repair = run_installer("--repair")
    assert repair.returncode == 0, repair.stdout + repair.stderr
    assert "Repairing the existing installation without pulling source" in repair.stdout
    assert setup_log.read_text(encoding="utf-8").splitlines() == ["setup", "setup"]
    assert user_data.read_text(encoding="utf-8") == '{"created": true, "custom": "keep"}'
    assert len(curl_log.read_text(encoding="utf-8").splitlines()) == 1
    assert len(clone_log.read_text(encoding="utf-8").splitlines()) == 1

    active_release = install_dir / "releases" / "v2.0.0"
    (active_release / "installer").mkdir(parents=True)
    (active_release / "installer" / "setup.sh").write_text(
        '#!/bin/bash\nprintf \'active setup:%s\\n\' "$PWD" >> "$SETUP_LOG"\n',
        encoding="utf-8",
    )
    (active_release / "installer" / "setup.sh").chmod(0o755)
    (active_release / "installer" / "backup_cleanup.sh").write_text(
        "#!/bin/bash\nexit 0\n", encoding="utf-8"
    )
    (install_dir / "current").symlink_to(active_release)
    environment["FAKE_CHMOD_DENY"] = "1"

    transactional_repair = run_installer("--repair")

    assert transactional_repair.returncode == 0, (
        transactional_repair.stdout + transactional_repair.stderr
    )
    assert setup_log.read_text(encoding="utf-8").splitlines() == [
        "setup",
        "setup",
        f"active setup:{active_release}",
    ]
    assert len(curl_log.read_text(encoding="utf-8").splitlines()) == 1
    assert len(clone_log.read_text(encoding="utf-8").splitlines()) == 1
    environment.pop("FAKE_CHMOD_DENY")

    outside_release = tmp_path / "outside-release"
    (outside_release / "installer").mkdir(parents=True)
    (outside_release / "installer" / "setup.sh").write_text(
        f"#!/bin/bash\n: > {tmp_path / 'external-setup-ran'}\n",
        encoding="utf-8",
    )
    (install_dir / "current").unlink()
    (install_dir / "current").symlink_to(outside_release)
    privileged_log.write_text("", encoding="utf-8")
    setup_log.write_text("", encoding="utf-8")

    invalid_repair = run_installer("--repair")

    assert invalid_repair.returncode == 2
    assert (
        "active release link points outside"
        in (invalid_repair.stdout + invalid_repair.stderr).lower()
    )
    assert setup_log.read_text(encoding="utf-8") == ""
    assert privileged_log.read_text(encoding="utf-8") == ""

    (install_dir / "current").unlink()
    (install_dir / "current").symlink_to(active_release)
    shutil.rmtree(active_release / "installer")
    (active_release / "installer").symlink_to(
        outside_release / "installer", target_is_directory=True
    )
    external_setup_marker = tmp_path / "external-setup-ran"
    external_setup_marker.unlink(missing_ok=True)

    symlinked_installer_repair = run_installer("--repair")

    assert symlinked_installer_repair.returncode == 2
    assert (
        "safe installer/setup.sh"
        in (symlinked_installer_repair.stdout + symlinked_installer_repair.stderr).lower()
    )
    assert setup_log.read_text(encoding="utf-8") == ""
    assert not external_setup_marker.exists()
