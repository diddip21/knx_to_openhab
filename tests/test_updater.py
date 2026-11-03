"""Tests for the web UI self-updater."""

import json
from unittest.mock import Mock

from web_ui.backend.updater import Updater


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
    assert (tmp_path / "update.log").read_text(encoding="utf-8").startswith(
        "Update queued for v1.4.0"
    )


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


def test_trigger_update_removes_queued_request_when_worker_service_cannot_start(
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

    success, message = Updater(base_path=str(tmp_path)).trigger_update()

    assert success is False
    assert "unit already running" in message
    assert not (data_dir / "update-request.json").exists()


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
