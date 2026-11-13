"""Execute the real setup and migration with allowlisted, isolated host operations."""

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
pytestmark = pytest.mark.skipif(
    sys.platform != "linux" or os.geteuid() != 0 or shutil.which("bash") is None,
    reason="real setup lock validation requires root-owned Linux temporary paths",
)


def executable(path, content):
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


@pytest.mark.parametrize("fault", ["helpers", "migration", "restart"])
def test_real_setup_restores_services_and_repairs_after_failure(tmp_path, monkeypatch, fault):
    source = tmp_path / "source"
    source.mkdir()
    shutil.copytree(ROOT / "installer", source / "installer")
    shutil.copytree(ROOT / "web_ui", source / "web_ui")
    shutil.copy2(ROOT / "config.json", source / "config.json")
    base, config, data, backups = [tmp_path / name for name in ("app", "config", "data", "backups")]
    shutil.copytree(source / "web_ui", base / "web_ui")
    (base / "config.json").write_text('{"rules":"custom"}\n')
    web_config = base / "web_ui/backend/config.json"
    web_config.write_text(
        json.dumps(
            {
                "jobs_dir": "var/lib/knx_to_openhab",
                "backups_dir": "var/backups/knx_to_openhab",
                "auth": {"enabled": True, "user": "tester", "password": "synthetic-secret"},
            }
        )
    )
    legacy_jobs = base / "var/lib/knx_to_openhab"
    legacy_jobs.mkdir(parents=True)
    upload = legacy_jobs / "upload.knxproj"
    upload.write_bytes(b"synthetic upload")
    (legacy_jobs / "jobs.json").write_text(json.dumps({"job-1": {"input": str(upload)}}))
    legacy_backups = base / "var/backups/knx_to_openhab"
    legacy_backups.mkdir(parents=True)
    (legacy_backups / "job-1.tar.gz").write_bytes(b"synthetic backup")
    venv = base / "venv/bin"
    venv.mkdir(parents=True)
    (venv / "python").symlink_to(sys.executable)
    lock = tmp_path / "locks/maintenance.lock"
    lock.parent.mkdir(mode=0o750)
    lock.touch(mode=0o640)
    registry = tmp_path / "registry/paths.env"
    registry.parent.mkdir()
    registry.write_text(
        "# Managed by installer/setup.sh; do not edit by hand.\n"
        + "".join(
            f"{key}='{value}'\n"
            for key, value in {
                "KNXOH_INSTALL_DIR": base,
                "KNXOH_CONFIG_DIR": config,
                "KNXOH_DATA_DIR": data,
                "KNXOH_BACKUP_DIR": backups,
                "KNXOH_MAINTENANCE_LOCK_FILE": lock,
            }.items()
        )
    )
    for path in ("etc/systemd/system", "usr/local/sbin"):
        (tmp_path / "host" / path).mkdir(parents=True)
    initial_active = ["knxohui.service", "knxohui-backup-cleanup.timer"]
    (tmp_path / "active.json").write_text(json.dumps(initial_active))
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    adapter = (ROOT / "tests/fixtures/setup_host.py").read_text()
    executable(fake_bin / "sudo", f"#!{sys.executable}\n" + adapter)
    executable(fake_bin / "getent", "#!/bin/sh\necho knxohui:x:0:\n")
    executable(fake_bin / "id", "#!/bin/sh\necho 997\n")
    env = os.environ | {
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "SETUP_SANDBOX": str(tmp_path),
        "KNXOH_PATHS_FILE": str(registry),
        "KNXOH_MAINTENANCE_LOCK_FILE": str(lock),
    }

    def repair(selected_fault):
        return subprocess.run(
            ["bash", str(source / "installer/setup.sh")],
            env=env | {"SETUP_FAULT": selected_fault},
            capture_output=True,
            text=True,
            timeout=45,
            check=False,
        )

    first = repair(fault)
    assert first.returncode != 0, first.stdout + first.stderr
    assert "restoring services" in first.stderr, first.stdout + first.stderr
    assert sorted(json.loads((tmp_path / "active.json").read_text())) == sorted(initial_active)
    assert (tmp_path / "host/usr/local/libexec/knx_to_openhab/launch_web.sh").is_file()
    for path in (upload, data / "jobs/upload.knxproj"):
        if path.exists():
            assert path.read_bytes() == b"synthetic upload"
    assert upload.exists() or (data / "jobs/upload.knxproj").exists()
    surviving_backup = legacy_backups / "job-1.tar.gz"
    if not surviving_backup.exists():
        surviving_backup = backups / "job-1.tar.gz"
    assert surviving_backup.read_bytes() == b"synthetic backup"

    second = repair("")
    assert second.returncode == 0, second.stdout + second.stderr
    assert "Installation complete" in second.stdout
    assert sorted(json.loads((tmp_path / "active.json").read_text())) == sorted(initial_active)
    assert (data / "jobs/upload.knxproj").read_bytes() == b"synthetic upload"
    assert (backups / "job-1.tar.gz").read_bytes() == b"synthetic backup"
    assert json.loads((data / "jobs/jobs.json").read_text())["job-1"]["input"] == str(
        data / "jobs/upload.knxproj"
    )
    for key, value in {"INSTALL": base, "CONFIG": config, "DATA": data, "BACKUP": backups}.items():
        monkeypatch.setenv(f"KNXOH_{key}_DIR", str(value))
    monkeypatch.setenv("KNXOH_PATHS_FILE", str(registry))
    assert verify_password(load_config(base)["auth"]["password_hash"], "synthetic-secret")
    import fcntl

    for path in (lock, data / "updater.lock"):
        with path.open("a") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
