"""Tests for the web UI self-updater."""

import fcntl
import json
import os
import stat
import threading
from unittest.mock import Mock

import pytest

from web_ui.backend.updater import Updater


def _allow_isolated_update_worker(monkeypatch):
    monkeypatch.setattr(Updater, "_update_worker_setup_error", lambda _self: None)


def test_trigger_update_passes_install_dir_and_selected_release(monkeypatch, tmp_path):
    update_script = tmp_path / "update.sh"
    update_script.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    data_dir = tmp_path / "data"
    monkeypatch.setenv("KNXOH_DATA_DIR", str(data_dir))
    start_service = Mock(return_value=Mock(returncode=0, stderr=""))
    monkeypatch.setattr("web_ui.backend.updater.subprocess.run", start_service)
    monkeypatch.setattr(
        Updater,
        "check_github_version",
        lambda _self: (
            True,
            {
                "release_tag": "v1.4.0",
                "commit_hash": "a" * 40,
                "commit_date": "2026-11-03T00:00:00Z",
                "commit_message": "Stable release",
                "author": "Release Bot",
            },
        ),
    )
    monkeypatch.setattr(Updater, "get_current_version", lambda _self: {"commit_hash": "old"})
    _allow_isolated_update_worker(monkeypatch)

    success, _ = Updater(base_path=str(tmp_path)).trigger_update()

    assert success is True
    start_service.assert_called_once_with(
        [
            "/usr/bin/sudo",
            "-n",
            "/usr/local/sbin/knxohui-service-update",
            "start-web-update",
        ],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    request = json.loads((data_dir / "update-request.json").read_text(encoding="utf-8"))
    assert request["schema_version"] == 1
    assert request["release_tag"] == "v1.4.0"
    assert request["commit_hash"] == "a" * 40
    assert request["commit_date"] == "2026-11-03T00:00:00Z"
    assert request["commit_message"] == "Stable release"
    assert request["author"] == "Release Bot"
    assert request["repository"] == "diddip21/knx_to_openhab"
    assert (
        (tmp_path / "update.log").read_text(encoding="utf-8").startswith("Update queued for v1.4.0")
    )


def test_trigger_update_fsyncs_request_directory_before_starting_worker(monkeypatch, tmp_path):
    (tmp_path / "update.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    data_dir = tmp_path / "data"
    monkeypatch.setenv("KNXOH_DATA_DIR", str(data_dir))
    monkeypatch.setattr(
        Updater,
        "check_github_version",
        lambda _self: (
            True,
            {
                "release_tag": "v1.4.0",
                "commit_hash": "a" * 40,
                "commit_date": "2026-11-03T00:00:00Z",
            },
        ),
    )
    monkeypatch.setattr(Updater, "get_current_version", lambda _self: {"commit_hash": "old"})
    _allow_isolated_update_worker(monkeypatch)

    events = []
    real_fsync = os.fsync
    real_link = os.link

    def record_fsync(descriptor):
        if stat.S_ISDIR(os.fstat(descriptor).st_mode):
            events.append("request_directory_fsync")
        return real_fsync(descriptor)

    def record_link(source, target, *args, **kwargs):
        result = real_link(source, target, *args, **kwargs)
        events.append("publish")
        return result

    def start_worker(*_args, **_kwargs):
        events.append("worker")
        return Mock(returncode=0, stderr="")

    monkeypatch.setattr("web_ui.backend.updater.os.fsync", record_fsync)
    monkeypatch.setattr("web_ui.backend.updater.os.link", record_link)
    monkeypatch.setattr("web_ui.backend.updater.subprocess.run", start_worker)

    success, _message = Updater(base_path=str(tmp_path)).trigger_update()

    assert success is True
    assert events.index("publish") < events.index("request_directory_fsync")
    assert events.index("request_directory_fsync") < events.index("worker")


def test_trigger_update_does_not_start_worker_if_request_directory_fsync_fails(
    monkeypatch, tmp_path
):
    (tmp_path / "update.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    data_dir = tmp_path / "data"
    monkeypatch.setenv("KNXOH_DATA_DIR", str(data_dir))
    monkeypatch.setattr(
        Updater,
        "check_github_version",
        lambda _self: (
            True,
            {
                "release_tag": "v1.4.0",
                "commit_hash": "a" * 40,
                "commit_date": "2026-11-03T00:00:00Z",
            },
        ),
    )
    monkeypatch.setattr(Updater, "get_current_version", lambda _self: {"commit_hash": "old"})
    _allow_isolated_update_worker(monkeypatch)
    real_fsync = os.fsync

    def fail_directory_fsync(descriptor):
        if stat.S_ISDIR(os.fstat(descriptor).st_mode):
            raise OSError("injected directory fsync failure")
        return real_fsync(descriptor)

    monkeypatch.setattr("web_ui.backend.updater.os.fsync", fail_directory_fsync)
    start_worker = Mock(return_value=Mock(returncode=0, stderr=""))
    monkeypatch.setattr("web_ui.backend.updater.subprocess.run", start_worker)

    success, message = Updater(base_path=str(tmp_path)).trigger_update()

    assert success is False
    assert "injected directory fsync failure" in message
    start_worker.assert_not_called()
    assert (data_dir / "update-request.json").is_file()


def test_trigger_update_log_before_publish_is_fsynced(monkeypatch, tmp_path):
    (tmp_path / "update.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    data_dir = tmp_path / "data"
    log_path = tmp_path / "update.log"
    log_path.write_text(
        "Update queued for v1.4.0 (request_id=" + "a" * 32 + ").\n"
        "Update completed successfully!\n",
        encoding="utf-8",
    )
    log_inode = log_path.stat().st_ino
    monkeypatch.setenv("KNXOH_DATA_DIR", str(data_dir))
    monkeypatch.setattr(
        Updater,
        "check_github_version",
        lambda _self: (
            True,
            {
                "release_tag": "v1.4.0",
                "commit_hash": "a" * 40,
                "commit_date": "2026-11-03T00:00:00Z",
            },
        ),
    )
    monkeypatch.setattr(Updater, "get_current_version", lambda _self: {"commit_hash": "old"})
    _allow_isolated_update_worker(monkeypatch)
    monkeypatch.setattr(
        "web_ui.backend.updater.subprocess.run", Mock(return_value=Mock(returncode=0, stderr=""))
    )
    real_fsync = os.fsync
    real_link = os.link
    events = []
    publication = {}

    def record_fsync(descriptor):
        if os.fstat(descriptor).st_ino == log_inode:
            events.append("log_fsync")
        return real_fsync(descriptor)

    def record_publication(source, target, *args, **kwargs):
        request = json.loads(open(source, encoding="utf-8").read())
        publication["log"] = log_path.read_text(encoding="utf-8")
        publication["request"] = request
        publication["log_fsynced"] = "log_fsync" in events
        events.append("publish")
        return real_link(source, target, *args, **kwargs)

    monkeypatch.setattr("web_ui.backend.updater.os.fsync", record_fsync)
    monkeypatch.setattr("web_ui.backend.updater.os.link", record_publication)

    success, _message = Updater(base_path=str(tmp_path)).trigger_update()

    expected_header = (
        f"Update queued for v1.4.0 (request_id={publication['request']['request_id']}).\n"
    )
    assert success is True
    assert publication["log"] == expected_header
    assert publication["log_fsynced"] is True
    assert events.index("log_fsync") < events.index("publish")
    assert log_path.read_text(encoding="utf-8") == expected_header


def test_trigger_update_runs_the_active_release_script_from_the_stable_install_root(
    monkeypatch, tmp_path
):
    current_release = tmp_path / "current"
    current_release.mkdir()
    update_script = current_release / "update.sh"
    update_script.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    monkeypatch.setenv("KNXOH_DATA_DIR", str(tmp_path / "data"))
    start_service = Mock(return_value=Mock(returncode=0, stderr=""))
    monkeypatch.setattr("web_ui.backend.updater.subprocess.run", start_service)
    monkeypatch.setattr(
        Updater,
        "check_github_version",
        lambda _self: (
            True,
            {
                "release_tag": "v1.4.0",
                "commit_hash": "a" * 40,
                "commit_date": "2026-11-03T00:00:00Z",
            },
        ),
    )
    monkeypatch.setattr(Updater, "get_current_version", lambda _self: {"commit_hash": "old"})
    _allow_isolated_update_worker(monkeypatch)

    success, _ = Updater(base_path=str(tmp_path)).trigger_update()

    assert success is True
    start_service.assert_called_once()


def test_get_current_version_reads_the_active_release_metadata(tmp_path):
    release_dir = tmp_path / "current"
    release_dir.mkdir()
    commit_hash = "b" * 40
    (release_dir / "version.json").write_text(
        '{"release_tag":"v1.4.0","commit_hash":"'
        + commit_hash
        + '","commit_date":"2026-11-03T00:00:00Z","commit_message":"Release"}',
        encoding="utf-8",
    )

    current = Updater(base_path=str(tmp_path)).get_current_version()

    assert current["commit_hash"] == commit_hash
    assert current["commit_short"] == commit_hash[:7]
    assert current["release_tag"] == "v1.4.0"
    assert current["commit_message"] == "Release"


def test_check_github_version_resolves_latest_stable_release_commit(monkeypatch):
    responses = [
        Mock(
            status_code=200,
            json=Mock(return_value={"tag_name": "v1.4.0", "prerelease": False, "draft": False}),
        ),
        Mock(
            status_code=200,
            json=Mock(
                return_value={
                    "sha": "release-commit",
                    "commit": {
                        "committer": {"date": "2026-11-03T00:00:00Z"},
                        "message": "Stable release",
                        "author": {"name": "Release Bot"},
                    },
                }
            ),
        ),
    ]
    get = Mock(side_effect=responses)
    monkeypatch.setattr("web_ui.backend.updater.requests.get", get)

    success, release = Updater().check_github_version()

    assert success is True
    assert release["release_tag"] == "v1.4.0"
    assert release["commit_hash"] == "release-commit"
    assert get.call_args_list[0].args[0].endswith("/releases/latest")
    assert get.call_args_list[1].args[0].endswith("/commits/v1.4.0")


def test_get_current_version_includes_exact_release_tag(monkeypatch):
    updater = Updater()
    commands = [
        (True, "release-commit"),
        (True, "2026-11-03 00:00:00 +0000"),
        (True, "Prerelease"),
        (True, "HEAD"),
        (True, "v1.5.0-rc.1"),
    ]
    run_git = Mock(side_effect=commands)
    monkeypatch.setattr(updater, "_run_git_command", run_git)

    current = updater.get_current_version()

    assert current["release_tag"] == "v1.5.0-rc.1"
    assert run_git.call_args_list[-1].args[0] == [
        "describe",
        "--tags",
        "--exact-match",
        "HEAD",
    ]


def test_check_github_version_rejects_prerelease_tag_from_stable_endpoint(monkeypatch):
    response = Mock(
        status_code=200,
        json=Mock(return_value={"tag_name": "v1.5.0-rc.1", "prerelease": False, "draft": False}),
    )
    get = Mock(return_value=response)
    monkeypatch.setattr("web_ui.backend.updater.requests.get", get)

    success, result = Updater().check_github_version()

    assert success is False
    assert result["error"] == "Latest stable release metadata is invalid"
    get.assert_called_once()


def test_update_worker_readiness_requires_installed_files_and_sudo_permission(
    monkeypatch, tmp_path
):
    unit = tmp_path / "knxohui-update.service"
    launcher = tmp_path / "launch_update.sh"
    web_launcher = tmp_path / "launch_web.sh"
    helper = tmp_path / "knxohui-service-update"
    setup_script = tmp_path / "current/installer/setup.sh"
    for path in (unit, launcher, web_launcher, helper, setup_script):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("installed", encoding="utf-8")

    monkeypatch.setattr("web_ui.backend.updater._UPDATE_WORKER_UNIT", unit)
    monkeypatch.setattr("web_ui.backend.updater._UPDATE_WORKER_LAUNCHER", launcher)
    monkeypatch.setattr("web_ui.backend.updater._WEB_UI_LAUNCHER", web_launcher)
    monkeypatch.setattr("web_ui.backend.updater._SERVICE_UPDATE_HELPER", str(helper))
    permission = Mock(return_value=Mock(returncode=0, stderr=""))
    monkeypatch.setattr("web_ui.backend.updater.subprocess.run", permission)
    updater = Updater(base_path=str(tmp_path))

    error = updater._update_worker_setup_error()

    assert error is not None
    assert "isolated update worker is not installed or authorized" in error
    assert "sudo bash" in error
    assert "current/installer/setup.sh" in error
    permission.assert_not_called()

    web_launcher.write_text("# KNXOH_BOOT_RECOVERY_VERSION=1-disabled\n", encoding="utf-8")
    error = updater._update_worker_setup_error()

    assert error is not None
    permission.assert_not_called()

    web_launcher.write_text("# KNXOH_BOOT_RECOVERY_VERSION=1\n", encoding="utf-8")
    permission.return_value.returncode = 1
    permission.return_value.stderr = "not permitted"
    error = updater._update_worker_setup_error()

    assert error is not None
    permission.assert_called_once()
    permission.return_value.returncode = 0
    assert updater._update_worker_setup_error() is None


def test_trigger_update_requires_worker_setup_before_queuing(monkeypatch, tmp_path):
    (tmp_path / "update.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    monkeypatch.setenv("KNXOH_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(
        Updater,
        "check_github_version",
        lambda _self: (
            True,
            {
                "release_tag": "v1.4.0",
                "commit_hash": "a" * 40,
                "commit_date": "2026-11-03T00:00:00Z",
            },
        ),
    )
    monkeypatch.setattr(Updater, "get_current_version", lambda _self: {"commit_hash": "old"})
    message = "Run setup before queueing an update"
    monkeypatch.setattr(Updater, "_update_worker_setup_error", lambda _self: message)
    start_service = Mock()
    monkeypatch.setattr("web_ui.backend.updater.subprocess.run", start_service)

    success, result = Updater(base_path=str(tmp_path)).trigger_update()

    assert success is False
    assert result == message
    assert not (tmp_path / "data/update-request.json").exists()
    assert not (tmp_path / "update.log").exists()
    start_service.assert_not_called()


def test_trigger_update_preserves_published_request_when_worker_service_cannot_start(
    monkeypatch, tmp_path
):
    update_script = tmp_path / "update.sh"
    update_script.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    data_dir = tmp_path / "data"
    monkeypatch.setenv("KNXOH_DATA_DIR", str(data_dir))
    start_service = Mock(return_value=Mock(returncode=1, stderr="unit already running"))
    monkeypatch.setattr("web_ui.backend.updater.subprocess.run", start_service)
    monkeypatch.setattr(
        Updater,
        "check_github_version",
        lambda _self: (
            True,
            {
                "release_tag": "v1.4.0",
                "commit_hash": "a" * 40,
                "commit_date": "2026-11-03T00:00:00Z",
            },
        ),
    )
    monkeypatch.setattr(Updater, "get_current_version", lambda _self: {"commit_hash": "old"})
    _allow_isolated_update_worker(monkeypatch)

    success, message = Updater(base_path=str(tmp_path)).trigger_update()

    assert success is False
    assert "unit already running" in message
    request = json.loads((data_dir / "update-request.json").read_text(encoding="utf-8"))
    assert request["release_tag"] == "v1.4.0"


def test_trigger_update_resumes_existing_pending_request(monkeypatch, tmp_path):
    (tmp_path / "update.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    data_dir = tmp_path / "data"
    request_path = data_dir / "update-request.json"
    data_dir.mkdir()
    pending_request = {
        "schema_version": 1,
        "request_id": "b" * 32,
        "release_tag": "v1.3.0",
        "commit_hash": "c" * 40,
        "commit_date": "2026-11-02T00:00:00Z",
        "commit_message": "Already queued release",
        "author": "Release Bot",
        "repository": "diddip21/knx_to_openhab",
    }
    request_bytes = (json.dumps(pending_request) + "\n").encode()
    request_path.write_bytes(request_bytes)
    log_path = tmp_path / "update.log"
    log_path.write_text("Existing request log\n", encoding="utf-8")
    monkeypatch.setenv("KNXOH_DATA_DIR", str(data_dir))
    check_version = Mock(side_effect=AssertionError("pending requests must not need GitHub"))
    monkeypatch.setattr(Updater, "check_github_version", check_version)
    monkeypatch.setattr(Updater, "get_current_version", lambda _self: {"commit_hash": "old"})
    _allow_isolated_update_worker(monkeypatch)

    def start_worker(*_args, **_kwargs):
        assert log_path.read_text(encoding="utf-8") == (
            "Update queued for v1.3.0 (request_id=" + "b" * 32 + ").\n"
        )
        return Mock(returncode=0, stderr="")

    start_service = Mock(side_effect=start_worker)
    monkeypatch.setattr("web_ui.backend.updater.subprocess.run", start_service)

    success, message = Updater(base_path=str(tmp_path)).trigger_update()

    assert success is True
    assert "v1.3.0" in message
    assert "request_id=" + "b" * 32 in message
    assert start_service.call_count == 1
    assert request_path.read_bytes() == request_bytes
    assert log_path.read_text(encoding="utf-8") == (
        "Update queued for v1.3.0 (request_id=" + "b" * 32 + ").\n"
    )
    check_version.assert_not_called()


def test_trigger_update_reports_request_that_won_publication_race(monkeypatch, tmp_path):
    (tmp_path / "update.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    data_dir = tmp_path / "data"
    monkeypatch.setenv("KNXOH_DATA_DIR", str(data_dir))
    monkeypatch.setattr(
        Updater,
        "check_github_version",
        lambda _self: (
            True,
            {
                "release_tag": "v1.4.0",
                "commit_hash": "a" * 40,
                "commit_date": "2026-11-03T00:00:00Z",
            },
        ),
    )
    monkeypatch.setattr(Updater, "get_current_version", lambda _self: {"commit_hash": "old"})
    _allow_isolated_update_worker(monkeypatch)
    raced_request = {
        "schema_version": 1,
        "request_id": "e" * 32,
        "release_tag": "v1.3.0",
        "commit_hash": "d" * 40,
        "commit_date": "2026-11-02T00:00:00Z",
        "commit_message": "Already published release",
        "author": "Release Bot",
        "repository": "diddip21/knx_to_openhab",
    }

    def publish_raced_request(_source, target):
        (data_dir / target).write_text(json.dumps(raced_request), encoding="utf-8")
        raise FileExistsError

    monkeypatch.setattr("web_ui.backend.updater.os.link", publish_raced_request)
    monkeypatch.setattr(
        "web_ui.backend.updater.subprocess.run", Mock(return_value=Mock(returncode=0, stderr=""))
    )

    success, message = Updater(base_path=str(tmp_path)).trigger_update()

    assert success is True
    assert "v1.3.0" in message
    assert "request_id=" + "e" * 32 in message


def test_trigger_update_preserves_pending_request_when_worker_is_running(monkeypatch, tmp_path):
    (tmp_path / "update.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    request_path = data_dir / "update-request.json"
    request_bytes = (
        json.dumps(
            {
                "schema_version": 1,
                "request_id": "c" * 32,
                "release_tag": "v1.3.0",
                "commit_hash": "d" * 40,
                "commit_date": "2026-11-02T00:00:00Z",
                "commit_message": "Pending release",
                "author": "Release Bot",
                "repository": "diddip21/knx_to_openhab",
            }
        )
        + "\n"
    ).encode()
    request_path.write_bytes(request_bytes)
    monkeypatch.setenv("KNXOH_DATA_DIR", str(data_dir))
    monkeypatch.setattr(
        Updater,
        "check_github_version",
        lambda _self: (
            True,
            {
                "release_tag": "v1.4.0",
                "commit_hash": "a" * 40,
                "commit_date": "2026-11-03T00:00:00Z",
            },
        ),
    )
    monkeypatch.setattr(Updater, "get_current_version", lambda _self: {"commit_hash": "old"})
    _allow_isolated_update_worker(monkeypatch)
    start_service = Mock(return_value=Mock(returncode=4, stderr="unit already running"))
    monkeypatch.setattr("web_ui.backend.updater.subprocess.run", start_service)

    success, message = Updater(base_path=str(tmp_path)).trigger_update()

    assert success is False
    assert "already running" in message
    assert start_service.call_count == 1
    assert request_path.read_bytes() == request_bytes


def test_concurrent_update_request_cannot_replace_the_request_being_started(monkeypatch, tmp_path):
    (tmp_path / "update.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    data_dir = tmp_path / "data"
    request_path = data_dir / "update-request.json"
    monkeypatch.setenv("KNXOH_DATA_DIR", str(data_dir))
    monkeypatch.setattr(
        Updater,
        "check_github_version",
        lambda _self: (
            True,
            {
                "release_tag": "v1.4.0",
                "commit_hash": "a" * 40,
                "commit_date": "2026-11-03T00:00:00Z",
            },
        ),
    )
    monkeypatch.setattr(Updater, "get_current_version", lambda _self: {"commit_hash": "old"})
    _allow_isolated_update_worker(monkeypatch)

    first_start_entered = threading.Event()
    allow_first_start_to_finish = threading.Event()
    first_request = {}

    def start_service(*_args, **_kwargs):
        if not first_start_entered.is_set():
            first_request.update(json.loads(request_path.read_text(encoding="utf-8")))
            first_start_entered.set()
            assert allow_first_start_to_finish.wait(timeout=5)
            return Mock(returncode=0, stderr="")
        return Mock(returncode=1, stderr="unit already running")

    start_mock = Mock(side_effect=start_service)
    monkeypatch.setattr("web_ui.backend.updater.subprocess.run", start_mock)
    first_result = {}
    first_thread = threading.Thread(
        target=lambda: first_result.setdefault(
            "value", Updater(base_path=str(tmp_path)).trigger_update()
        )
    )
    first_thread.start()
    try:
        assert first_start_entered.wait(timeout=5)
        second_success, second_message = Updater(base_path=str(tmp_path)).trigger_update()
    finally:
        allow_first_start_to_finish.set()
        first_thread.join(timeout=5)

    assert not first_thread.is_alive()
    assert first_result["value"][0] is True
    assert second_success is False
    assert "progress" in second_message.lower()
    assert start_mock.call_count == 1
    assert json.loads(request_path.read_text(encoding="utf-8")) == first_request


def test_trigger_update_does_not_publish_while_worker_holds_request_lock(monkeypatch, tmp_path):
    (tmp_path / "update.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    lock_path = data_dir / "update-request.lock"
    log_path = tmp_path / "update.log"
    log_path.write_text("worker owns request\n", encoding="utf-8")
    monkeypatch.setenv("KNXOH_DATA_DIR", str(data_dir))
    check_version = Mock(
        return_value=(
            True,
            {
                "release_tag": "v1.4.0",
                "commit_hash": "a" * 40,
                "commit_date": "2026-11-03T00:00:00Z",
            },
        )
    )
    monkeypatch.setattr(Updater, "check_github_version", check_version)
    monkeypatch.setattr(Updater, "get_current_version", lambda _self: {"commit_hash": "old"})
    _allow_isolated_update_worker(monkeypatch)
    start_service = Mock(return_value=Mock(returncode=0, stderr=""))
    monkeypatch.setattr("web_ui.backend.updater.subprocess.run", start_service)

    with lock_path.open("a", encoding="utf-8") as held_lock:
        fcntl.flock(held_lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        success, message = Updater(base_path=str(tmp_path)).trigger_update()

    assert success is False
    assert "progress" in message.lower()
    check_version.assert_not_called()
    start_service.assert_not_called()
    assert not (data_dir / "update-request.json").exists()
    assert log_path.read_text(encoding="utf-8") == "worker owns request\n"


def test_trigger_update_creates_private_request_lock(monkeypatch, tmp_path):
    (tmp_path / "update.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    data_dir = tmp_path / "data"
    monkeypatch.setenv("KNXOH_DATA_DIR", str(data_dir))
    monkeypatch.setattr(
        Updater,
        "check_github_version",
        lambda _self: (
            True,
            {
                "release_tag": "v1.4.0",
                "commit_hash": "a" * 40,
                "commit_date": "2026-11-03T00:00:00Z",
            },
        ),
    )
    monkeypatch.setattr(Updater, "get_current_version", lambda _self: {"commit_hash": "old"})
    _allow_isolated_update_worker(monkeypatch)
    monkeypatch.setattr(
        "web_ui.backend.updater.subprocess.run", Mock(return_value=Mock(returncode=0, stderr=""))
    )

    success, _message = Updater(base_path=str(tmp_path)).trigger_update()

    assert success is True
    lock_path = data_dir / "update-request.lock"
    assert stat.S_IMODE(lock_path.stat().st_mode) == 0o600


def test_check_for_updates_does_not_downgrade_a_newer_prerelease(monkeypatch):
    updater = Updater()
    monkeypatch.setattr(
        updater,
        "get_current_version",
        lambda: {
            "commit_hash": "prerelease-commit",
            "commit_short": "prerele",
            "commit_date": "2026-11-03",
            "commit_message": "Prerelease",
            "release_tag": "v1.5.0-rc.1",
        },
    )
    monkeypatch.setattr(
        updater,
        "check_github_version",
        lambda: (
            True,
            {
                "commit_hash": "stable-commit",
                "commit_short": "stablec",
                "commit_date": "2026-10-01",
                "commit_message": "Stable",
                "author": "Release Bot",
                "release_tag": "v1.4.0",
            },
        ),
    )

    result = updater.check_for_updates()

    assert result["update_available"] is False
    assert result["latest_release_tag"] == "v1.4.0"
    assert result["current_release_tag"] == "v1.5.0-rc.1"


def test_trigger_update_refuses_to_downgrade_a_newer_prerelease(monkeypatch, tmp_path):
    updater = Updater(base_path=str(tmp_path))
    (tmp_path / "update.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    monkeypatch.setattr(
        updater,
        "get_current_version",
        lambda: {"commit_hash": "prerelease-commit", "release_tag": "v1.5.0-rc.1"},
    )
    monkeypatch.setattr(
        updater,
        "check_github_version",
        lambda: (True, {"release_tag": "v1.4.0", "commit_hash": "stable-commit"}),
    )
    start_service = Mock()
    monkeypatch.setattr("web_ui.backend.updater.subprocess.run", start_service)

    success, message = updater.trigger_update()

    assert success is False
    assert "newer than the latest stable release" in message
    start_service.assert_not_called()


def test_trigger_update_rejects_invalid_commit_metadata_before_queueing(monkeypatch, tmp_path):
    updater = Updater(base_path=str(tmp_path))
    (tmp_path / "update.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    start_service = Mock()
    monkeypatch.setattr("web_ui.backend.updater.subprocess.run", start_service)
    monkeypatch.setattr(
        updater,
        "check_github_version",
        lambda: (True, {"release_tag": "v1.4.0", "commit_hash": "bad"}),
    )
    monkeypatch.setattr(updater, "get_current_version", lambda: {"commit_hash": "old"})

    success, message = updater.trigger_update()

    assert success is False
    assert "commit hash" in message
    start_service.assert_not_called()
    assert not (tmp_path / "var/lib/knx_to_openhab/update-request.json").exists()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("commit_message", "message\rwith carriage return"),
        ("commit_message", "message\x00with NUL"),
        ("author", "author\rwith carriage return"),
        ("author", "author\x00with NUL"),
    ],
)
def test_trigger_update_rejects_control_characters_before_queueing(
    monkeypatch, tmp_path, field, value
):
    updater = Updater(base_path=str(tmp_path))
    (tmp_path / "update.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    monkeypatch.setenv("KNXOH_DATA_DIR", str(tmp_path / "data"))
    release = {
        "release_tag": "v1.4.0",
        "commit_hash": "a" * 40,
        "commit_date": "2026-11-03T00:00:00Z",
        "commit_message": "Stable release",
        "author": "Release Bot",
    }
    release[field] = value
    monkeypatch.setattr(updater, "check_github_version", lambda: (True, release))
    monkeypatch.setattr(updater, "get_current_version", lambda: {"commit_hash": "old"})
    monkeypatch.setattr(updater, "_update_worker_setup_error", lambda: None)
    start_worker = Mock(return_value=Mock(returncode=0, stderr=""))
    monkeypatch.setattr("web_ui.backend.updater.subprocess.run", start_worker)

    success, message = updater.trigger_update()

    assert success is False
    assert field.replace("_", " ") in message.lower()
    start_worker.assert_not_called()
    data_dir = tmp_path / "data"
    assert not (data_dir / "update-request.json").exists()
    assert not (data_dir / "update-request.running.json").exists()
    assert not list(data_dir.glob(".update-request-*.tmp"))


def test_build_metadata_release_update_is_not_suppressed(monkeypatch, tmp_path):
    updater = Updater(base_path=str(tmp_path))
    (tmp_path / "update.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    monkeypatch.setenv("KNXOH_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(
        updater,
        "get_current_version",
        lambda: {
            "commit_hash": "build-one-commit",
            "commit_short": "build1",
            "commit_date": "2026-11-01",
            "commit_message": "Build one",
            "release_tag": "v1.4.0+build.1",
        },
    )
    monkeypatch.setattr(
        updater,
        "check_github_version",
        lambda: (
            True,
            {
                "commit_hash": "c" * 40,
                "commit_short": "build2",
                "commit_date": "2026-11-03",
                "commit_message": "Build two",
                "author": "Release Bot",
                "release_tag": "v1.4.0+build.2",
            },
        ),
    )
    start_service = Mock(return_value=Mock(returncode=0, stderr=""))
    monkeypatch.setattr("web_ui.backend.updater.subprocess.run", start_service)
    _allow_isolated_update_worker(monkeypatch)

    status = updater.check_for_updates()
    success, _ = updater.trigger_update()

    assert status["update_available"] is True
    assert success is True
    assert start_service.call_count == 1


def test_check_github_version_caches_resolved_release(monkeypatch):
    responses = [
        Mock(
            status_code=200,
            json=Mock(return_value={"tag_name": "v1.4.0", "prerelease": False, "draft": False}),
        ),
        Mock(
            status_code=200,
            json=Mock(
                return_value={
                    "sha": "release-commit",
                    "commit": {
                        "committer": {"date": "2026-11-03T00:00:00Z"},
                        "message": "Stable release",
                        "author": {"name": "Release Bot"},
                    },
                }
            ),
        ),
    ]
    get = Mock(side_effect=responses)
    monkeypatch.setattr("web_ui.backend.updater.requests.get", get)
    updater = Updater()

    first_success, first_release = updater.check_github_version()
    second_success, second_release = updater.check_github_version()

    assert (first_success, first_release) == (second_success, second_release)
    assert second_release["release_tag"] == "v1.4.0"
    assert get.call_count == 2
