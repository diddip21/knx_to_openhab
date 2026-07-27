"""Tests for the web UI self-updater."""

import os
from unittest.mock import Mock

from web_ui.backend.updater import Updater


def test_trigger_update_passes_actual_install_dir(monkeypatch, tmp_path):
    """The update script must receive the path used to construct the updater."""
    update_script = tmp_path / "update.sh"
    update_script.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    popen = Mock()
    monkeypatch.setattr("web_ui.backend.updater.subprocess.Popen", popen)

    success, _ = Updater(base_path=str(tmp_path)).trigger_update()

    assert success is True
    popen.assert_called_once()
    args, kwargs = popen.call_args
    assert args[0] == ["/bin/bash", str(update_script)]
    assert kwargs["cwd"] == str(tmp_path)
    assert kwargs["env"]["INSTALL_DIR"] == str(tmp_path)
    assert kwargs["env"]["LOG_FILE"] == os.devnull
