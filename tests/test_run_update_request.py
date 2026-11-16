"""Tests for the isolated, systemd-managed updater worker."""

import fcntl
import json
import os
import stat
import subprocess
import sys
import time
from unittest.mock import Mock

import pytest

from installer import run_update_request


def _configure_paths(monkeypatch, tmp_path):
    install = tmp_path / "install"
    config = tmp_path / "config"
    data = tmp_path / "data"
    backups = tmp_path / "backups"
    for path in (install, config, data, backups):
        path.mkdir()
    monkeypatch.setenv("KNXOH_INSTALL_DIR", str(install))
    monkeypatch.setenv("KNXOH_CONFIG_DIR", str(config))
    monkeypatch.setenv("KNXOH_DATA_DIR", str(data))
    monkeypatch.setenv("KNXOH_BACKUP_DIR", str(backups))
    monkeypatch.setenv("KNXOH_PATHS_FILE", str(tmp_path / "missing-paths.env"))
    return install, data


def _request(**overrides):
    result = {
        "schema_version": 1,
        "request_id": "a" * 32,
        "release_tag": "v1.4.0",
        "commit_hash": "b" * 40,
        "commit_date": "2026-11-03T00:00:00Z",
        "commit_message": "Release candidate",
        "author": "Release Bot",
        "repository": "diddip21/knx_to_openhab",
    }
    result.update(overrides)
    return result


def test_worker_runs_the_selected_release_from_a_stable_systemd_unit(monkeypatch, tmp_path):
    install, data = _configure_paths(monkeypatch, tmp_path)
    active_release = install / "current"
    active_release.mkdir()
    update_script = active_release / "update.sh"
    update_script.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    (data / "update-request.json").write_text(json.dumps(_request()), encoding="utf-8")
    run_update = Mock(return_value=Mock(returncode=0))
    monkeypatch.setattr(run_update_request.subprocess, "run", run_update)

    result = run_update_request.run_update_request()

    assert result == 0
    run_update.assert_called_once()
    args, kwargs = run_update.call_args
    assert args[0] == ["/bin/bash", str(update_script)]
    assert kwargs["cwd"] == install
    assert kwargs["env"]["RELEASE_TAG"] == "v1.4.0"
    assert kwargs["env"]["UPDATE_REQUEST_ID"] == "a" * 32
    assert kwargs["env"]["RELEASE_COMMIT_HASH"] == "b" * 40
    assert kwargs["env"]["RELEASE_COMMIT_MESSAGE"] == "Release candidate"
    assert kwargs["env"]["KNXOH_GITHUB_REPOSITORY"] == "diddip21/knx_to_openhab"
    assert kwargs["stdout"].name == str(install / "update.log")
    assert not (data / "update-request.json").exists()
    assert not (data / "update-request.running.json").exists()
    update_log = (install / "update.log").read_text(encoding="utf-8")
    assert "Starting isolated updater for v1.4.0" in update_log
    assert "Update completed successfully! (request_id=" + "a" * 32 + ")" in update_log


def test_worker_rejects_unexpected_repository_without_running_update(monkeypatch, tmp_path):
    install, data = _configure_paths(monkeypatch, tmp_path)
    (data / "update-request.json").write_text(
        json.dumps(_request(repository="attacker/other")), encoding="utf-8"
    )
    run_update = Mock()
    monkeypatch.setattr(run_update_request.subprocess, "run", run_update)

    result = run_update_request.run_update_request()

    assert result == 1
    run_update.assert_not_called()
    assert not (data / "update-request.json").exists()
    assert "unexpected repository" in (install / "update.log").read_text(encoding="utf-8")


@pytest.mark.parametrize("failure", ["missing_script", "spawn_error"])
def test_worker_preserves_request_when_update_never_starts(monkeypatch, tmp_path, failure):
    install, data = _configure_paths(monkeypatch, tmp_path)
    request_path = data / "update-request.json"
    running_path = data / "update-request.running.json"
    request_bytes = json.dumps(_request()).encode()
    request_path.write_bytes(request_bytes)
    run_update = Mock(side_effect=OSError("could not spawn updater"))
    monkeypatch.setattr(run_update_request.subprocess, "run", run_update)
    if failure == "spawn_error":
        (install / "update.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")

    result = run_update_request.run_update_request()

    assert result == 1
    assert request_path.exists() is False
    assert running_path.read_bytes() == request_bytes
    if failure == "missing_script":
        run_update.assert_not_called()
    else:
        run_update.assert_called_once()


def test_worker_recovers_a_stale_running_request_when_lock_is_free(monkeypatch, tmp_path):
    install, data = _configure_paths(monkeypatch, tmp_path)
    (install / "update.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    running_path = data / "update-request.running.json"
    running_path.write_text(json.dumps(_request()), encoding="utf-8")
    run_update = Mock(return_value=Mock(returncode=0))
    monkeypatch.setattr(run_update_request.subprocess, "run", run_update)

    result = run_update_request.run_update_request()

    assert result == 0
    run_update.assert_called_once()
    assert run_update.call_args.kwargs["env"]["RELEASE_TAG"] == "v1.4.0"
    assert not (data / "update-request.json").exists()
    assert not running_path.exists()


def test_worker_preserves_pending_and_running_request_conflict(monkeypatch, tmp_path):
    install, data = _configure_paths(monkeypatch, tmp_path)
    (install / "update.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    pending_path = data / "update-request.json"
    running_path = data / "update-request.running.json"
    pending_bytes = json.dumps(_request(request_id="a" * 32)).encode()
    running_bytes = json.dumps(_request(request_id="b" * 32)).encode()
    pending_path.write_bytes(pending_bytes)
    running_path.write_bytes(running_bytes)
    run_update = Mock(return_value=Mock(returncode=0))
    monkeypatch.setattr(run_update_request.subprocess, "run", run_update)

    result = run_update_request.run_update_request()

    assert result == 1
    run_update.assert_not_called()
    assert pending_path.read_bytes() == pending_bytes
    assert running_path.read_bytes() == running_bytes
    assert (
        "both pending and running" in (install / "update.log").read_text(encoding="utf-8").lower()
    )


def test_worker_holds_private_request_lock_while_update_script_runs(monkeypatch, tmp_path):
    install, data = _configure_paths(monkeypatch, tmp_path)
    (install / "update.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    (data / "update-request.json").write_text(json.dumps(_request()), encoding="utf-8")
    lock_path = data / "update-request.lock"
    worker_held_lock = []

    def run_update(*_args, **_kwargs):
        with lock_path.open("a", encoding="utf-8") as probe:
            try:
                fcntl.flock(probe.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                worker_held_lock.append(True)
            else:
                worker_held_lock.append(False)
                fcntl.flock(probe.fileno(), fcntl.LOCK_UN)
        return Mock(returncode=0)

    monkeypatch.setattr(run_update_request.subprocess, "run", run_update)

    result = run_update_request.run_update_request()

    assert result == 0
    assert worker_held_lock == [True]
    assert stat.S_IMODE(lock_path.stat().st_mode) == 0o600
    with lock_path.open("a", encoding="utf-8") as probe:
        fcntl.flock(probe.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(probe.fileno(), fcntl.LOCK_UN)


def test_update_process_keeps_request_lock_if_worker_dies(monkeypatch, tmp_path):
    install, data = _configure_paths(monkeypatch, tmp_path)
    continue_path = tmp_path / "continue-update"
    started_path = tmp_path / "update-started"
    (install / "update.sh").write_text(
        "#!/usr/bin/env bash\n"
        f"touch '{started_path}'\n"
        f"while [[ ! -e '{continue_path}' ]]; do sleep 0.02; done\n",
        encoding="utf-8",
    )
    (data / "update-request.json").write_text(json.dumps(_request()), encoding="utf-8")
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(run_update_request.APP_ROOT)
    worker = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "from installer.run_update_request import run_update_request; "
            "raise SystemExit(run_update_request())",
        ],
        cwd=run_update_request.APP_ROOT,
        env=environment,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    lock_path = data / "update-request.lock"
    try:
        deadline = time.monotonic() + 10
        while not started_path.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert started_path.exists(), "updater child did not start"
        worker.kill()
        worker.wait(timeout=5)

        with lock_path.open("a", encoding="utf-8") as probe:
            with pytest.raises(BlockingIOError):
                fcntl.flock(probe.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

        continue_path.touch()
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            with lock_path.open("a", encoding="utf-8") as probe:
                try:
                    fcntl.flock(probe.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    pass
                else:
                    fcntl.flock(probe.fileno(), fcntl.LOCK_UN)
                    break
            time.sleep(0.02)
        else:
            raise AssertionError("updater child did not release the inherited request lock")
    finally:
        continue_path.touch(exist_ok=True)
        if worker.poll() is None:
            worker.kill()
            worker.wait(timeout=5)
