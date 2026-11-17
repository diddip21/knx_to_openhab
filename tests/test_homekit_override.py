"""Tests for the HomeKit tri-state override and its consistent defaults.

Issue #89: ``general.homekit_enabled`` overrides the ETS project detection as a
tri-state (missing → ETS comment decides, true → forced on, false → forced
off). String booleans must be evaluated strictly, so the string "false" never
counts as enabled.
"""

import importlib
import json
from types import SimpleNamespace
from unittest.mock import Mock, mock_open

import pytest

import knxproject_to_openhab
from web_ui.backend import app as app_module
from web_ui.backend.project_preview import (
    build_project_preview,
    get_general_config,
    resolve_homekit_enabled,
)


def _project(comment):
    return {"info": {"comment": comment}}


def _override_resolver(_project, general):
    """Fake ``resolve_homekit_mode``: ETS detection is on, the override decides."""
    override = (general or {}).get("homekit_enabled")
    return True if override is None else bool(override)


class TestResolveHomeKitMode:
    def test_missing_general_config_uses_ets_detection(self):
        resolve = knxproject_to_openhab.resolve_homekit_mode
        assert resolve(_project("homekit=true"), None) is True
        assert resolve(_project("homekit=true"), {}) is True
        assert resolve(_project("homekit=false"), {}) is False
        assert resolve(_project(""), {}) is False

    def test_override_forces_enabled_despite_ets_comment(self):
        resolve = knxproject_to_openhab.resolve_homekit_mode
        assert resolve(_project(""), {"homekit_enabled": True}) is True
        assert resolve(_project("homekit=false"), {"homekit_enabled": True}) is True

    def test_override_forces_disabled_despite_ets_comment(self):
        resolve = knxproject_to_openhab.resolve_homekit_mode
        assert resolve(_project("homekit=true"), {"homekit_enabled": False}) is False

    def test_string_boolean_values_are_evaluated_strictly(self):
        resolve = knxproject_to_openhab.resolve_homekit_mode
        assert resolve(_project(""), {"homekit_enabled": "true"}) is True
        assert resolve(_project("homekit=true"), {"homekit_enabled": "false"}) is False
        assert resolve(_project(""), {"homekit_enabled": "1"}) is True
        assert resolve(_project("homekit=true"), {"homekit_enabled": "0"}) is False
        assert resolve(_project("homekit=true"), {"homekit_enabled": "yes"}) is True
        assert resolve(_project("homekit=true"), {"homekit_enabled": "no"}) is False

    def test_none_value_falls_back_to_ets_detection(self):
        resolve = knxproject_to_openhab.resolve_homekit_mode
        assert resolve(_project("homekit=true"), {"homekit_enabled": None}) is True
        assert resolve(_project(""), {"homekit_enabled": None}) is False


class TestCoerceBool:
    def test_booleans_pass_through(self):
        coerce = knxproject_to_openhab.coerce_bool
        assert coerce(True) is True
        assert coerce(False) is False

    def test_strings_are_strict(self):
        coerce = knxproject_to_openhab.coerce_bool
        for truthy in ("yes", "true", "t", "1", "YES", "True"):
            assert coerce(truthy) is True, truthy
        for falsy in ("no", "false", "f", "0", "FALSE", ""):
            assert coerce(falsy) is False, falsy

    def test_none_returns_default(self):
        coerce = knxproject_to_openhab.coerce_bool
        assert coerce(None) is False
        assert coerce(None, default=True) is True

    def test_non_string_scalars_use_python_truthiness(self):
        coerce = knxproject_to_openhab.coerce_bool
        assert coerce(1) is True
        assert coerce(0) is False
        assert coerce([]) is False


class TestPreviewHelper:
    def test_get_general_config_reads_generator_config_dict(self):
        module = SimpleNamespace(config={"general": {"homekit_enabled": True}})
        assert get_general_config(module) == {"homekit_enabled": True}

    def test_get_general_config_tolerates_missing_config(self):
        assert get_general_config(SimpleNamespace()) is None
        assert get_general_config(SimpleNamespace(config=None)) is None

    def test_resolve_homekit_enabled_prefers_resolver(self):
        module = SimpleNamespace(
            is_homekit_enabled=lambda _project: True,
            resolve_homekit_mode=lambda _project, general: (general or {}).get("x") == 1,
        )
        assert resolve_homekit_enabled(module, {}, {"x": 1}) is True
        assert resolve_homekit_enabled(module, {}, {"x": 0}) is False

    def test_resolve_homekit_enabled_falls_back_to_ets_detection(self):
        module = SimpleNamespace(is_homekit_enabled=lambda _project: True)
        assert resolve_homekit_enabled(module, {}, None) is True


@pytest.fixture
def client():
    if not getattr(app_module, "FLASK_AVAILABLE", False):
        pytest.skip("Flask not available")
    app_module.app.testing = True
    if getattr(app_module, "cfg", None) is not None:
        app_module.cfg.setdefault("auth", {})
        app_module.cfg["auth"]["enabled"] = False
    return app_module.app.test_client()


def test_config_roundtrip_keeps_homekit_false_and_neighbor_keys(client, monkeypatch):
    """Saving HomeKit options must not lose an explicit false or sibling keys."""
    previous_config = {
        "general": {
            "FloorNameAsItIs": True,
            "homekit_enabled": True,
            "homekit_rollershutter_sendUpDownForExtents": False,
        }
    }
    new_config = {
        "general": {
            "FloorNameAsItIs": True,
            "homekit_enabled": False,
            "homekit_rollershutter_sendUpDownForExtents": False,
            "homekit_rollershutter_stop": False,
            "homekit_rollershutter_stopSameDirection": False,
        }
    }
    saved_configs = []
    monkeypatch.setattr(app_module, "load_generator_config", lambda _root: previous_config)
    monkeypatch.setattr(
        app_module,
        "get_paths",
        lambda _root: SimpleNamespace(secrets_file=None),
    )
    monkeypatch.setattr(
        app_module,
        "save_generator_config",
        lambda config, _root: saved_configs.append(json.loads(json.dumps(config))),
    )

    response = client.post("/api/config", json=new_config)

    assert response.status_code == 200
    assert len(saved_configs) == 1
    general = saved_configs[0]["general"]
    assert general["homekit_enabled"] is False
    assert general["homekit_rollershutter_sendUpDownForExtents"] is False
    assert general["homekit_rollershutter_stop"] is False
    assert general["homekit_rollershutter_stopSameDirection"] is False
    assert general["FloorNameAsItIs"] is True


def test_project_preview_endpoint_reports_effective_homekit_value(client, monkeypatch):
    """The preview must report the override-aware value, not the raw ETS flag."""
    fake_knx_module = SimpleNamespace(
        create_building=lambda project: {"building": True},
        get_addresses=lambda project: [],
        put_addresses_in_building=lambda building, addresses, project: [
            {"name_long": "Project", "floors": []}
        ],
        get_gateway_ip=lambda project: "1.2.3.4",
        # ETS says enabled, the stored configuration forces it off.
        is_homekit_enabled=lambda project: True,
        resolve_homekit_mode=_override_resolver,
        is_alexa_enabled=lambda project: False,
        config={"general": {"homekit_enabled": False}},
    )
    mocked_open = mock_open(read_data=json.dumps({"project": "data"}))
    monkeypatch.setattr("builtins.open", mocked_open)

    def fake_import_module(name):
        return fake_knx_module

    monkeypatch.setattr(importlib, "import_module", fake_import_module)

    job_mgr = Mock()
    job_mgr.get_job.return_value = {"id": "abc", "input": "/tmp/input.json", "password": None}
    monkeypatch.setattr(app_module, "job_mgr", job_mgr)
    monkeypatch.setattr(app_module.os.path, "exists", lambda path: path == "/tmp/input.json")

    response = client.get("/api/job/abc/preview")

    assert response.status_code == 200
    assert response.get_json()["metadata"]["homekit_enabled"] is False
