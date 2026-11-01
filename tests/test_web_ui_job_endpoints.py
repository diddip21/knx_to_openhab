import importlib
import json
import subprocess
import threading
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


def test_config_change_provisions_new_yaml_path_with_fixed_root_action(client, monkeypatch):
    previous_config = {
        "output_format": "yaml",
        "yaml_path": "openhab/yaml/knx.yaml",
        "sitemap_label": "House",
    }
    new_config = {
        **previous_config,
        "yaml_path": "openhab/yaml/secondary.yaml",
        "sitemap_label": "Home",
    }
    saved_configs = []
    provision = Mock(return_value=SimpleNamespace(returncode=0, stdout="", stderr=""))
    monkeypatch.setattr(app_module, "load_generator_config", lambda _root: previous_config)
    monkeypatch.setattr(
        app_module,
        "get_paths",
        lambda _root: SimpleNamespace(secrets_file="/etc/knx_to_openhab/secrets.env"),
    )
    monkeypatch.setattr(
        app_module,
        "save_generator_config",
        lambda config, _root: saved_configs.append(config.copy()),
    )
    monkeypatch.setattr(subprocess, "run", provision)

    response = client.post("/api/config", json=new_config)

    assert response.status_code == 200
    assert saved_configs == [new_config]
    provision.assert_called_once()
    assert provision.call_args.args[0] == [
        "sudo",
        "-n",
        "/usr/local/sbin/knxohui-service-update",
        "provision-yaml",
    ]


def test_config_change_restores_yaml_path_when_provisioning_fails(client, monkeypatch):
    previous_config = {
        "output_format": "yaml",
        "yaml_path": "openhab/yaml/knx.yaml",
        "sitemap_label": "House",
    }
    new_config = {
        **previous_config,
        "yaml_path": "openhab/yaml/secondary.yaml",
        "sitemap_label": "Home",
    }
    saved_configs = []
    provision = Mock(
        return_value=SimpleNamespace(returncode=1, stdout="", stderr="target rejected")
    )
    monkeypatch.setattr(app_module, "load_generator_config", lambda _root: previous_config)
    monkeypatch.setattr(
        app_module,
        "get_paths",
        lambda _root: SimpleNamespace(secrets_file="/etc/knx_to_openhab/secrets.env"),
    )
    monkeypatch.setattr(
        app_module,
        "save_generator_config",
        lambda config, _root: saved_configs.append(config.copy()),
    )
    monkeypatch.setattr(subprocess, "run", provision)

    response = client.post("/api/config", json=new_config)

    assert response.status_code == 500
    assert [config["yaml_path"] for config in saved_configs] == [
        "openhab/yaml/secondary.yaml",
        "openhab/yaml/knx.yaml",
    ]
    assert saved_configs[-1]["sitemap_label"] == "Home"
    assert response.get_json() == {"error": "Unable to provision YAML output: target rejected"}


def test_config_change_skips_root_provisioning_in_local_development(client, monkeypatch):
    previous_config = {"yaml_path": "openhab/yaml/knx.yaml"}
    new_config = {"yaml_path": "openhab/yaml/secondary.yaml"}
    provision = Mock()
    monkeypatch.setattr(app_module, "load_generator_config", lambda _root: previous_config)
    monkeypatch.setattr(
        app_module,
        "get_paths",
        lambda _root: SimpleNamespace(secrets_file=None),
    )
    monkeypatch.setattr(app_module, "save_generator_config", lambda _config, _root: None)
    monkeypatch.setattr(subprocess, "run", provision)

    response = client.post("/api/config", json=new_config)

    assert response.status_code == 200
    provision.assert_not_called()


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

    mocked_open = mock_open(read_data=json.dumps({"project": "data"}))
    monkeypatch.setattr("builtins.open", mocked_open)
    monkeypatch.setattr(importlib, "import_module", lambda name: fake_knx_module)

    resp = client.get("/api/job/abc/preview")

    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload["metadata"]["project_name"] == "Project"
    assert payload["metadata"]["gateway_ip"] == "1.2.3.4"
    assert payload["metadata"]["homekit_enabled"] is True
    assert payload["metadata"]["alexa_enabled"] is False
    assert payload["metadata"]["unknown_items"]


def test_job_preview_uses_cached_projection_after_password_cleanup(client, monkeypatch):
    """A completed encrypted job can still show its preview without its password."""
    cached_preview = {
        "metadata": {"project_name": "Project", "total_addresses": 1},
        "buildings": [],
    }
    job_mgr = Mock()
    job_mgr.get_job.return_value = {"id": "abc", "input": "/missing/encrypted.knxproj"}
    job_mgr.get_job_preview.return_value = cached_preview
    monkeypatch.setattr(app_module, "job_mgr", job_mgr)

    response = client.get("/api/job/abc/preview")

    assert response.status_code == 200
    assert response.get_json() == cached_preview
    job_mgr.get_job_preview.assert_called_once_with("abc")


def test_gateway_state_returns_active_format_detected_source_and_unverified_status(
    client, monkeypatch
):
    job_mgr = Mock()
    job_mgr.get_gateway_state.return_value = {
        "things_format": "yaml",
        "managed_path": "yaml/knx.yaml",
        "configured_path": "openhab/yaml/knx.yaml",
        "gateway_ip": "192.168.1.10",
        "gateway_mode": "TUNNEL",
        "saved_override": "192.168.1.10",
        "reset_available": True,
        "detected_gateway_ip": "192.168.1.5",
    }
    job_mgr.get_last_deployed_gateway_source.return_value = {
        "job_id": "deployed-job",
        "detected_gateway_ip": "192.168.1.5",
        "things_format": "dsl",
    }
    monkeypatch.setattr(app_module, "job_mgr", job_mgr)

    response = client.get("/api/gateway/state")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["things_format"] == "yaml"
    assert payload["active_path"] == "openhab/yaml/knx.yaml"
    assert payload["gateway_ip"] == "192.168.1.10"
    assert payload["detected_gateway_ip"] == "192.168.1.5"
    assert payload["reset_available"] is True
    assert payload["runtime_status"] == "not_checked"
    job_mgr.get_gateway_state.assert_called_once_with()
    job_mgr.get_last_deployed_gateway_source.assert_called_once_with()


def test_gateway_api_requires_authentication_when_auth_is_enabled(client, monkeypatch):
    monkeypatch.setitem(
        app_module.cfg,
        "auth",
        {"enabled": True, "user": "operator", "legacy_password": "configured"},
    )
    job_mgr = Mock()
    monkeypatch.setattr(app_module, "job_mgr", job_mgr)

    response = client.get("/api/gateway/state")

    assert response.status_code == 401
    assert response.get_json() == {"error": "authentication required"}
    job_mgr.get_gateway_state.assert_not_called()


@pytest.mark.parametrize("ip_address", ["192.168.1.55", "2001:0db8::1"])
def test_gateway_ip_route_delegates_valid_ip_and_reports_file_only_success(
    client, monkeypatch, ip_address
):
    job_mgr = Mock()
    job_mgr.apply_gateway_ip.return_value = {
        "success": True,
        "gateway_ip": ip_address,
        "message": "KNX gateway configuration file updated; OpenHAB runtime status was not checked.",
    }
    monkeypatch.setattr(app_module, "job_mgr", job_mgr)

    response = client.post("/api/gateway/ip", json={"ip_address": ip_address})

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["success"] is True
    assert payload["gateway_ip"] == ip_address
    assert payload["runtime_status"] == "not_checked"
    assert "file updated" in payload["message"]
    assert "runtime status was not checked" in payload["message"]
    job_mgr.apply_gateway_ip.assert_called_once_with(ip_address)


@pytest.mark.parametrize("payload", [{}, {"ip_address": ""}, {"ip_address": "bad-ip"}])
def test_gateway_ip_route_returns_400_for_invalid_input(client, monkeypatch, payload):
    job_mgr = Mock()
    job_mgr.apply_gateway_ip.side_effect = ValueError("Invalid IP address: bad-ip")
    monkeypatch.setattr(app_module, "job_mgr", job_mgr)

    response = client.post("/api/gateway/ip", json=payload)

    assert response.status_code == 400
    assert "error" in response.get_json()
    if payload.get("ip_address"):
        job_mgr.apply_gateway_ip.assert_called_once_with(payload["ip_address"])
    else:
        job_mgr.apply_gateway_ip.assert_not_called()


def test_gateway_ip_route_maps_missing_or_ambiguous_source_to_conflict(client, monkeypatch):
    job_mgr = Mock()
    job_mgr.apply_gateway_ip.side_effect = ValueError("Multiple KNX bridge definitions found")
    monkeypatch.setattr(app_module, "job_mgr", job_mgr)

    response = client.post("/api/gateway/ip", json={"ip_address": "192.168.1.55"})

    assert response.status_code == 409
    assert "Multiple KNX bridge" in response.get_json()["error"]


def test_gateway_ip_route_maps_file_errors_to_server_error(client, monkeypatch):
    job_mgr = Mock()
    job_mgr.apply_gateway_ip.side_effect = OSError("managed file is not writable")
    monkeypatch.setattr(app_module, "job_mgr", job_mgr)

    response = client.post("/api/gateway/ip", json={"ip_address": "192.168.1.55"})

    assert response.status_code == 500
    assert "managed file is not writable" in response.get_json()["error"]


def test_gateway_reset_route_delegates_and_reports_router_reset(client, monkeypatch):
    job_mgr = Mock()
    job_mgr.restore_gateway_ip.return_value = {
        "success": True,
        "gateway_mode": "ROUTER",
        "message": "KNX gateway configuration file updated; OpenHAB runtime status was not checked.",
    }
    monkeypatch.setattr(app_module, "job_mgr", job_mgr)

    response = client.post("/api/gateway/ip/reset")

    assert response.status_code == 200
    assert response.get_json()["gateway_mode"] == "ROUTER"
    assert response.get_json()["runtime_status"] == "not_checked"
    job_mgr.restore_gateway_ip.assert_called_once_with()


def test_gateway_reset_route_returns_conflict_without_deployed_source(client, monkeypatch):
    job_mgr = Mock()
    job_mgr.restore_gateway_ip.side_effect = ValueError(
        "No successfully deployed ETS gateway source is available"
    )
    monkeypatch.setattr(app_module, "job_mgr", job_mgr)

    response = client.post("/api/gateway/ip/reset")

    assert response.status_code == 409
    assert "deployed ETS gateway source" in response.get_json()["error"]


def test_gateway_undo_route_delegates_and_reports_file_only_success(client, monkeypatch):
    job_mgr = Mock()
    job_mgr.undo_gateway_ip.return_value = {
        "success": True,
        "undo_available": False,
        "message": "KNX gateway file restored; OpenHAB runtime status was not checked.",
    }
    monkeypatch.setattr(app_module, "job_mgr", job_mgr)

    response = client.post("/api/gateway/ip/undo")

    assert response.status_code == 200
    assert response.get_json()["success"] is True
    assert response.get_json()["undo_available"] is False
    assert response.get_json()["runtime_status"] == "not_checked"
    job_mgr.undo_gateway_ip.assert_called_once_with()


def test_gateway_undo_route_returns_conflict_for_unavailable_or_stale_snapshot(client, monkeypatch):
    job_mgr = Mock()
    job_mgr.undo_gateway_ip.side_effect = ValueError("Undo snapshot is stale")
    monkeypatch.setattr(app_module, "job_mgr", job_mgr)

    response = client.post("/api/gateway/ip/undo")

    assert response.status_code == 409
    assert response.get_json() == {"error": "Undo snapshot is stale"}


def test_gateway_undo_route_requires_authentication_when_enabled(client, monkeypatch):
    monkeypatch.setitem(
        app_module.cfg,
        "auth",
        {"enabled": True, "user": "operator", "legacy_password": "configured"},
    )
    job_mgr = Mock()
    monkeypatch.setattr(app_module, "job_mgr", job_mgr)

    response = client.post("/api/gateway/ip/undo")

    assert response.status_code == 401
    assert response.get_json() == {"error": "authentication required"}
    job_mgr.undo_gateway_ip.assert_not_called()


def test_gateway_state_maps_missing_bridge_to_conflict(client, monkeypatch):
    job_mgr = Mock()
    job_mgr.get_gateway_state.side_effect = ValueError("KNX bridge not found")
    monkeypatch.setattr(app_module, "job_mgr", job_mgr)

    response = client.get("/api/gateway/state")

    assert response.status_code == 409
    assert "KNX bridge not found" in response.get_json()["error"]


def test_config_save_uses_gateway_operation_lock(client, monkeypatch):
    operation_lock = threading.Lock()
    gateway_state_lock = threading.Lock()
    job_mgr = Mock()
    job_mgr.operation_lock = operation_lock
    job_mgr.gateway_state_lock = gateway_state_lock
    monkeypatch.setattr(app_module, "job_mgr", job_mgr)
    monkeypatch.setattr(
        app_module,
        "get_paths",
        lambda _root: SimpleNamespace(secrets_file=None),
    )
    saved = {}

    def save_while_locked(config, _project_root):
        assert operation_lock.locked()
        assert gateway_state_lock.locked()
        saved.update(config)

    monkeypatch.setattr(app_module, "save_generator_config", save_while_locked)

    config = {
        "output_format": "legacy",
        "yaml_path": "openhab/yaml/knx.yaml",
        "devices": {"gateway": {"ip_address": "192.168.1.10"}},
        "general": {"custom_sibling": True},
    }
    response = client.post("/api/config", json=config)

    assert response.status_code == 200
    assert saved == config
    assert not operation_lock.locked()


def test_config_save_provisions_changed_yaml_path_under_operation_lock(client, monkeypatch):
    operation_lock = threading.Lock()
    gateway_state_lock = threading.Lock()
    job_mgr = Mock()
    job_mgr.operation_lock = operation_lock
    job_mgr.gateway_state_lock = gateway_state_lock
    monkeypatch.setattr(app_module, "job_mgr", job_mgr)
    monkeypatch.setattr(
        app_module,
        "get_paths",
        lambda _root: SimpleNamespace(secrets_file="/etc/knx-to-openhab/secrets.json"),
    )
    previous = {
        "output_format": "legacy",
        "yaml_path": "openhab/yaml/old.yaml",
        "general": {"existing": True},
    }
    monkeypatch.setattr(app_module, "load_generator_config", lambda _root: previous)
    saves = []

    def save_while_locked(config, _project_root):
        assert operation_lock.locked()
        assert gateway_state_lock.locked()
        saves.append(config.copy())

    monkeypatch.setattr(app_module, "save_generator_config", save_while_locked)
    command_calls = []

    def provision(*args, **kwargs):
        assert operation_lock.locked()
        assert gateway_state_lock.locked()
        command_calls.append((args, kwargs))
        return SimpleNamespace(returncode=0, stderr="", stdout="")

    monkeypatch.setattr(app_module.subprocess, "run", provision)
    config = {
        "output_format": "yaml",
        "yaml_path": "openhab/yaml/new.yaml",
        "things_path": "openhab/things/knx.things",
        "general": {"existing": True, "new_setting": "keep"},
        "devices": {"gateway": {"ip_address": "192.168.1.50"}},
    }

    response = client.post("/api/config", json=config)

    assert response.status_code == 200
    assert saves == [config]
    assert len(command_calls) == 1
    assert command_calls[0][0][0][0] == "sudo"
    assert not operation_lock.locked()


def test_config_save_provision_failure_rolls_back_only_yaml_path(client, monkeypatch):
    operation_lock = threading.Lock()
    gateway_state_lock = threading.Lock()
    job_mgr = Mock()
    job_mgr.operation_lock = operation_lock
    job_mgr.gateway_state_lock = gateway_state_lock
    monkeypatch.setattr(app_module, "job_mgr", job_mgr)
    monkeypatch.setattr(
        app_module,
        "get_paths",
        lambda _root: SimpleNamespace(secrets_file="/etc/knx-to-openhab/secrets.json"),
    )
    previous = {"yaml_path": "openhab/yaml/old.yaml", "legacy_sibling": "preserve"}
    monkeypatch.setattr(app_module, "load_generator_config", lambda _root: previous)
    saves = []

    def save_while_locked(config, _project_root):
        assert operation_lock.locked()
        assert gateway_state_lock.locked()
        saves.append(config.copy())

    monkeypatch.setattr(app_module, "save_generator_config", save_while_locked)
    monkeypatch.setattr(
        app_module.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=1, stderr="provision denied", stdout=""
        ),
    )
    config = {
        "output_format": "yaml",
        "yaml_path": "openhab/yaml/new.yaml",
        "general": {"new_sibling": "preserve"},
        "devices": {"gateway": {"ip_address": "192.168.1.70"}},
    }

    response = client.post("/api/config", json=config)

    assert response.status_code == 500
    assert "provision denied" in response.get_json()["error"]
    assert saves[0] == config
    assert saves[1] == {
        **config,
        "yaml_path": "openhab/yaml/old.yaml",
    }
    assert not operation_lock.locked()
