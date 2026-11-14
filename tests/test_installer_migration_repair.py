"""CLI repair after an interrupted real runtime-data migration."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from web_ui.backend.auth import verify_password
from web_ui.backend.storage import load_config

ROOT = Path(__file__).resolve().parents[1]


def _is_debian_based_linux() -> bool:
    if not sys.platform.startswith("linux") or shutil.which("bash") is None:
        return False
    try:
        release = Path("/etc/os-release").read_text(encoding="utf-8")
    except OSError:
        return False
    values = dict(line.split("=", 1) for line in release.splitlines() if "=" in line)
    release_ids = {values.get("ID", "").strip('"'), *values.get("ID_LIKE", "").strip('"').split()}
    return "debian" in release_ids


pytestmark = pytest.mark.skipif(
    not _is_debian_based_linux(), reason="the installer requires Debian-based Linux utilities"
)


def _executable(path: Path, contents: str) -> None:
    path.write_text(contents, encoding="utf-8")
    path.chmod(0o755)


def test_repair_retries_real_migration_after_path_publication_failure(tmp_path, monkeypatch):
    install_dir = tmp_path / "install"
    installer_dir = install_dir / "installer"
    installer_dir.mkdir(parents=True)
    template_dir = tmp_path / "template"
    template_dir.mkdir()
    config_dir = tmp_path / "config"
    data_dir = tmp_path / "data"
    backup_dir = tmp_path / "backups"
    paths_file = tmp_path / "paths.env"
    paths_file.mkdir()
    setup_log = tmp_path / "setup.log"
    unexpected_log = tmp_path / "unexpected.log"

    legacy_jobs = install_dir / "var/lib/knx_to_openhab"
    legacy_backups = install_dir / "var/backups/knx_to_openhab"
    legacy_jobs.mkdir(parents=True)
    legacy_backups.mkdir(parents=True)
    upload = legacy_jobs / "upload.knxproj"
    upload.write_text("synthetic project", encoding="utf-8")
    (legacy_jobs / "jobs.json").write_text(
        json.dumps({"job-1": {"id": "job-1", "input": str(upload)}}), encoding="utf-8"
    )
    (legacy_backups / "job-1.tar.gz").write_bytes(b"synthetic backup")
    legacy_web_config = install_dir / "web_ui/backend/config.json"
    legacy_web_config.parent.mkdir(parents=True)
    legacy_web_config.write_text(
        json.dumps(
            {
                "jobs_dir": "var/lib/knx_to_openhab",
                "backups_dir": "var/backups/knx_to_openhab",
                "auth": {"enabled": True, "user": "tester", "password": "synthetic-secret"},
            }
        ),
        encoding="utf-8",
    )
    (install_dir / "config.json").write_text('{"rules":"custom"}\n', encoding="utf-8")
    (template_dir / "config.json").write_text('{"rules":"default"}\n', encoding="utf-8")

    _executable(
        installer_dir / "setup.sh",
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'echo setup >> "$SETUP_LOG"\n'
        'python3 "$REAL_MIGRATION_SCRIPT" \\\n'
        '  --source-root "$KNXOH_INSTALL_DIR" --template-root "$MIGRATION_TEMPLATE_ROOT" \\\n'
        '  --config-dir "$KNXOH_CONFIG_DIR" --data-dir "$KNXOH_DATA_DIR" \\\n'
        '  --backup-dir "$KNXOH_BACKUP_DIR" --install-dir "$KNXOH_INSTALL_DIR" \\\n'
        '  --paths-file "$MIGRATION_PATHS_FILE"\n',
    )
    (installer_dir / "web_ui_endpoint.py").write_text(
        'print("loopback\\n127.0.0.1\\n8085")\n', encoding="utf-8"
    )

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _executable(
        fake_bin / "sudo",
        "#!/usr/bin/env bash\n"
        'if [[ "${1:-}" == -n && "${2:-}" == true ]]; then exit 0; fi\n'
        'if [[ "${1:-}" == apt-get ]]; then exit 0; fi\n'
        'exec "$@"\n',
    )
    _executable(
        fake_bin / "dpkg",
        "#!/usr/bin/env bash\n"
        "for package in git python3 python3-venv python3-pip rsync curl; do\n"
        '  printf "ii  %s 1.0 all installed\\n" "$package"\n'
        "done\n",
    )
    _executable(fake_bin / "hostname", "#!/usr/bin/env bash\necho 127.0.0.1\n")
    for command in ("curl", "git"):
        _executable(
            fake_bin / command,
            '#!/usr/bin/env bash\necho "$0 $*" >> "$UNEXPECTED_LOG"\nexit 99\n',
        )

    environment = os.environ.copy()
    environment.update(
        {
            "ALLOW_ROOT": "1",
            "KNXOH_INSTALL_DIR": str(install_dir),
            "KNXOH_CONFIG_DIR": str(config_dir),
            "KNXOH_DATA_DIR": str(data_dir),
            "KNXOH_BACKUP_DIR": str(backup_dir),
            "REAL_MIGRATION_SCRIPT": str(ROOT / "installer/migrate_runtime_data.py"),
            "MIGRATION_TEMPLATE_ROOT": str(template_dir),
            "MIGRATION_PATHS_FILE": str(paths_file),
            "SETUP_LOG": str(setup_log),
            "UNEXPECTED_LOG": str(unexpected_log),
            "PATH": f"{fake_bin}{os.pathsep}{environment['PATH']}",
        }
    )

    def repair():
        return subprocess.run(
            ["bash", str(ROOT / "install.sh"), "--repair"],
            env=environment,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )

    first = repair()
    assert first.returncode != 0
    assert "Setup script failed" in first.stdout
    assert upload.read_text(encoding="utf-8") == "synthetic project"
    assert (legacy_backups / "job-1.tar.gz").read_bytes() == b"synthetic backup"
    assert json.loads((data_dir / "jobs/jobs.json").read_text(encoding="utf-8"))["job-1"][
        "input"
    ] == str(upload)
    assert not unexpected_log.exists()

    paths_file.rmdir()
    second = repair()
    assert second.returncode == 0, second.stdout + second.stderr
    assert setup_log.read_text(encoding="utf-8").splitlines() == ["setup", "setup"]
    assert not legacy_jobs.exists()
    assert not legacy_backups.exists()
    assert (data_dir / "jobs/upload.knxproj").read_text(encoding="utf-8") == "synthetic project"
    assert (backup_dir / "job-1.tar.gz").read_bytes() == b"synthetic backup"
    assert json.loads((data_dir / "jobs/jobs.json").read_text(encoding="utf-8"))["job-1"][
        "input"
    ] == str(data_dir / "jobs/upload.knxproj")
    assert not unexpected_log.exists()

    monkeypatch.setenv("KNXOH_INSTALL_DIR", str(install_dir))
    monkeypatch.setenv("KNXOH_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("KNXOH_DATA_DIR", str(data_dir))
    monkeypatch.setenv("KNXOH_BACKUP_DIR", str(backup_dir))
    monkeypatch.setenv("KNXOH_PATHS_FILE", str(paths_file))
    assert verify_password(load_config(install_dir)["auth"]["password_hash"], "synthetic-secret")
