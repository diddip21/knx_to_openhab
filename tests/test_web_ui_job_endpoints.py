import importlib
import json
from types import SimpleNamespace
from unittest.mock import Mock, mock_open

import pytest

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


def test_job_deploy_success(client, monkeypatch):
    job_mgr = Mock()
    job_mgr.deploy.return_value = (True, "deployed")
    monkeypatch.setattr(app_module, "job_mgr", job_mgr)

    resp = client.post("/api/job/abc/deploy")

    assert resp.status_code == 200
    assert resp.get_json() == {"success": True, "message": "deployed"}
    job_mgr.deploy.assert_called_once_with("abc")


def test_job_deploy_not_found(client, monkeypatch):
    job_mgr = Mock()
    job_mgr.deploy.side_effect = ValueError("job not found")
    monkeypatch.setattr(app_module, "job_mgr", job_mgr)

    resp = client.post("/api/job/missing/deploy")

    assert resp.status_code == 404
    assert resp.get_json() == {"error": "job not found"}


def test_job_rollback_success(client, monkeypatch):
    job_mgr = Mock()
    job_mgr.rollback.return_value = (True, "rolled back")
    monkeypatch.setattr(app_module, "job_mgr", job_mgr)

    resp = client.post("/api/job/abc/rollback", json={"backup": "backup.tgz"})

    assert resp.status_code == 200
    assert resp.get_json() == {"ok": True, "output": "rolled back"}
    job_mgr.rollback.assert_called_once_with("abc", "backup.tgz")


def test_job_diff_success(client, monkeypatch):
    job_mgr = Mock()
    job_mgr.get_job.return_value = {
        "id": "abc",
        "stats": {"items/knx.items": {}},
    }
    job_mgr.get_file_diff.return_value = ["-old", "+new"]
    monkeypatch.setattr(app_module, "job_mgr", job_mgr)

    resp = client.get("/api/job/abc/diff")

    assert resp.status_code == 200
    assert resp.get_json() == {"items/knx.items": ["-old", "+new"]}
    job_mgr.get_file_diff.assert_called_once_with("abc", "items/knx.items")


def test_job_diff_missing_stats(client, monkeypatch):
    job_mgr = Mock()
    job_mgr.get_job.return_value = {"id": "abc", "stats": {}}
    monkeypatch.setattr(app_module, "job_mgr", job_mgr)

    resp = client.get("/api/job/abc/diff")

    assert resp.status_code == 400
    assert resp.get_json() == {"error": "no stats available"}


def test_job_delete_success(client, monkeypatch):
    job_mgr = Mock()
    job_mgr.delete_job.return_value = True
    monkeypatch.setattr(app_module, "job_mgr", job_mgr)

    resp = client.delete("/api/job/abc")

    assert resp.status_code == 200
    assert resp.get_json() == {"ok": True}
    job_mgr.delete_job.assert_called_once_with("abc")


def test_job_preview_success(client, monkeypatch):
    job_mgr = Mock()
    job_mgr.get_job.return_value = {"id": "abc", "input": "/tmp/input.json", "password": None}
    monkeypatch.setattr(app_module, "job_mgr", job_mgr)

    def fake_exists(path):
        return path == "/tmp/input.json"

    monkeypatch.setattr(app_module.os.path, "exists", fake_exists)

    fake_knx_module = SimpleNamespace(
        create_building=lambda project: {"building": True},
        get_addresses=lambda project: [
            {"Group name": "Light", "Address": "1/2/3", "Floor": "", "Room": ""}
        ],
        put_addresses_in_building=lambda building, addresses, project: [
            {
                "name_long": "Project",
                "floors": [
                    {
                        "rooms": [
                            {
                                "Addresses": [{"Group name": "Light", "Address": "1/2/3"}],
                                "devices": [],
                            }
                        ]
                    }
                ],
            }
        ],
        get_gateway_ip=lambda project: "1.2.3.4",
        is_homekit_enabled=lambda project: True,
        is_alexa_enabled=lambda project: False,
    )

    monkeypatch.setattr(importlib, "import_module", lambda name: fake_knx_module)

    mocked_open = mock_open(read_data=json.dumps({"project": "data"}))
    monkeypatch.setattr("builtins.open", mocked_open)

    resp = client.get("/api/job/abc/preview")

    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload["metadata"]["project_name"] == "Project"
    assert payload["metadata"]["gateway_ip"] == "1.2.3.4"
    assert payload["metadata"]["homekit_enabled"] is True
    assert payload["metadata"]["alexa_enabled"] is False
    assert payload["metadata"]["unknown_items"]


