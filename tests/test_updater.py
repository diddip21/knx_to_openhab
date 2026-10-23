"""Tests for the web UI self-updater."""

import os
import subprocess
from pathlib import Path
from unittest.mock import Mock

from web_ui.backend.updater import Updater


def test_trigger_update_passes_actual_install_dir(monkeypatch, tmp_path):
    """The update script must receive the path used to construct the updater."""
    update_script = tmp_path / "update.sh"
    update_script.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    popen = Mock()
    monkeypatch.setattr("web_ui.backend.updater.subprocess.Popen", popen)
    monkeypatch.setattr(Updater, "get_current_version", lambda self: {"branch": "main"})

    success, _ = Updater(base_path=str(tmp_path)).trigger_update()

    assert success is True
    popen.assert_called_once()
    args, kwargs = popen.call_args
    assert args[0] == ["/bin/bash", str(update_script)]
    assert kwargs["cwd"] == str(tmp_path)
    assert kwargs["env"]["INSTALL_DIR"] == str(tmp_path)
    assert kwargs["env"]["LOG_FILE"] == os.devnull


def test_preview_branch_cannot_offer_or_trigger_main_update(monkeypatch, tmp_path):
    updater = Updater(base_path=str(tmp_path))
    monkeypatch.setattr(
        updater,
        "get_current_version",
        lambda: {"branch": "developer/feature-upgrade", "commit_short": "abc123"},
    )
    remote = Mock(side_effect=AssertionError("must not check main"))
    monkeypatch.setattr(updater, "check_github_version", remote)
    popen = Mock(side_effect=AssertionError("must not launch update"))
    monkeypatch.setattr("web_ui.backend.updater.subprocess.Popen", popen)

    status = updater.check_for_updates()
    success, message = updater.trigger_update()

    assert status["update_available"] is False
    assert "only available on main" in status["error"]
    assert success is False
    assert "only available on main" in message
    remote.assert_not_called()
    popen.assert_not_called()


def test_update_script_rejects_preview_branch_before_backup_or_service_changes(tmp_path):
    repo = tmp_path / "candidate"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "developer/feature-upgrade", str(repo)], check=True)
    backup_dir = tmp_path / "backups"
    log_file = tmp_path / "update.log"
    env = os.environ.copy()
    env.update(
        {"INSTALL_DIR": str(repo), "KNXOH_BACKUP_DIR": str(backup_dir), "LOG_FILE": str(log_file)}
    )

    result = subprocess.run(
        ["bash", str(Path(__file__).resolve().parents[1] / "update.sh")],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    assert "only available on main" in log_file.read_text(encoding="utf-8")
    assert not backup_dir.exists()
