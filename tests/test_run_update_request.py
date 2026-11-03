"""Tests for the isolated, systemd-managed updater worker."""

import json
from unittest.mock import Mock

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
    assert kwargs["env"]["RELEASE_COMMIT_HASH"] == "b" * 40
    assert kwargs["env"]["RELEASE_COMMIT_MESSAGE"] == "Release candidate"
    assert kwargs["env"]["KNXOH_GITHUB_REPOSITORY"] == "diddip21/knx_to_openhab"
    assert kwargs["stdout"].name == str(install / "update.log")
    assert not (data / "update-request.json").exists()
    assert not (data / "update-request.running.json").exists()
    assert "Starting isolated updater for v1.4.0" in (install / "update.log").read_text(
        encoding="utf-8"
    )


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
