import pytest
from unittest.mock import Mock

from web_ui.backend import app as app_module


@pytest.fixture
def client():
    if not getattr(app_module, "FLASK_AVAILABLE", False):
        pytest.skip("Flask not available")
    app_module.app.testing = True
    if getattr(app_module, "cfg", None) is not None:
        app_module.cfg.setdefault("auth", {})
        app_module.cfg["auth"]["enabled"] = False
    return app_module.app.test_client()


def test_get_version_returns_payload(client, monkeypatch):
    updater = Mock()
    updater.get_current_version.return_value = {"commit_hash": "abc123"}
    monkeypatch.setattr(app_module, "updater", updater)

    resp = client.get("/api/version")

    assert resp.status_code == 200
    assert resp.get_json() == {"commit_hash": "abc123"}
    updater.get_current_version.assert_called_once_with()


def test_check_version_returns_payload(client, monkeypatch):
    updater = Mock()
    updater.check_for_updates.return_value = {"update_available": False}
    monkeypatch.setattr(app_module, "updater", updater)

    resp = client.get("/api/version/check")

    assert resp.status_code == 200
    assert resp.get_json() == {"update_available": False}
    updater.check_for_updates.assert_called_once_with()


def test_trigger_update_windows_simulation(client, monkeypatch):
    monkeypatch.setattr(app_module.sys, "platform", "win32")

    resp = client.post("/api/version/update")

    assert resp.status_code == 200
    assert resp.get_json()["status"] == "simulated"


def test_trigger_update_success(client, monkeypatch):
    monkeypatch.setattr(app_module.sys, "platform", "linux")
    updater = Mock()
    updater.trigger_update.return_value = (True, "Update started")
    monkeypatch.setattr(app_module, "updater", updater)

    resp = client.post("/api/version/update")

    assert resp.status_code == 200
    assert resp.get_json() == {
        "status": "updating",
        "message": "Update started",
    }
    updater.trigger_update.assert_called_once_with()


def test_trigger_update_failure(client, monkeypatch):
    monkeypatch.setattr(app_module.sys, "platform", "linux")
    updater = Mock()
    updater.trigger_update.return_value = (False, "Update failed")
    monkeypatch.setattr(app_module, "updater", updater)

    resp = client.post("/api/version/update")

    assert resp.status_code == 500
    assert resp.get_json() == {"error": "Update failed"}
    updater.trigger_update.assert_called_once_with()


def test_update_log_returns_payload(client, monkeypatch):
    updater = Mock()
    updater.get_update_log.return_value = "log content"
    monkeypatch.setattr(app_module, "updater", updater)

    resp = client.get("/api/version/log")

    assert resp.status_code == 200
    assert resp.get_json() == {"log": "log content"}
    updater.get_update_log.assert_called_once_with()
