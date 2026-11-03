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

    success, _ = Updater(base_path=str(tmp_path)).trigger_update()

    assert success is True
    assert popen.call_count == 2
    assert popen.call_args.kwargs["env"]["RELEASE_TAG"] == "v1.4.0"
