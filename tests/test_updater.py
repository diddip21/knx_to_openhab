"""Tests for the web UI self-updater."""

import os
from unittest.mock import Mock

from web_ui.backend.updater import Updater


def test_trigger_update_passes_install_dir_and_selected_release(monkeypatch, tmp_path):
    update_script = tmp_path / "update.sh"
    update_script.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    popen = Mock()
    monkeypatch.setattr("web_ui.backend.updater.subprocess.Popen", popen)
    monkeypatch.setattr(
        Updater,
        "check_github_version",
        lambda _self: (True, {"release_tag": "v1.4.0", "commit_hash": "release-commit"}),
    )
    monkeypatch.setattr(Updater, "get_current_version", lambda _self: {"commit_hash": "old"})

    success, _ = Updater(base_path=str(tmp_path)).trigger_update()

    assert success is True
    popen.assert_called_once()
    args, kwargs = popen.call_args
    assert args[0] == ["/bin/bash", str(update_script)]
    assert kwargs["cwd"] == str(tmp_path)
    assert kwargs["env"]["INSTALL_DIR"] == str(tmp_path)
    assert kwargs["env"]["LOG_FILE"] == os.devnull
    assert kwargs["env"]["RELEASE_TAG"] == "v1.4.0"


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


def test_trigger_update_preserves_release_tag_when_log_redirection_fails(monkeypatch, tmp_path):
    update_script = tmp_path / "update.sh"
    update_script.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    popen = Mock(side_effect=[OSError("log redirection failed"), None])
    monkeypatch.setattr("web_ui.backend.updater.subprocess.Popen", popen)
    monkeypatch.setattr(
        Updater,
        "check_github_version",
        lambda _self: (True, {"release_tag": "v1.4.0", "commit_hash": "release-commit"}),
    )
    monkeypatch.setattr(Updater, "get_current_version", lambda _self: {"commit_hash": "old"})

    success, _ = Updater(base_path=str(tmp_path)).trigger_update()

    assert success is True
    assert popen.call_count == 2
    assert popen.call_args.kwargs["env"]["RELEASE_TAG"] == "v1.4.0"


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
    popen = Mock()
    monkeypatch.setattr("web_ui.backend.updater.subprocess.Popen", popen)

    success, message = updater.trigger_update()

    assert success is False
    assert "newer than the latest stable release" in message
    popen.assert_not_called()


def test_build_metadata_release_update_is_not_suppressed(monkeypatch, tmp_path):
    updater = Updater(base_path=str(tmp_path))
    (tmp_path / "update.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")
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
                "commit_hash": "build-two-commit",
                "commit_short": "build2",
                "commit_date": "2026-11-03",
                "commit_message": "Build two",
                "author": "Release Bot",
                "release_tag": "v1.4.0+build.2",
            },
        ),
    )
    popen = Mock()
    monkeypatch.setattr("web_ui.backend.updater.subprocess.Popen", popen)

    status = updater.check_for_updates()
    success, _ = updater.trigger_update()

    assert status["update_available"] is True
    assert success is True
    assert popen.call_count == 1
