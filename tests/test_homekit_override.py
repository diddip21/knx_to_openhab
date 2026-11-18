"""Tests for the HomeKit tri-state override and preview/config round trips."""

from copy import deepcopy
from types import SimpleNamespace

import pytest

import knxproject_to_openhab
from knxproject_to_openhab import coerce_bool, resolve_homekit_mode
from web_ui.backend.project_preview import build_project_preview


@pytest.fixture
def client():
    from web_ui.backend import app as app_module

    if not getattr(app_module, "FLASK_AVAILABLE", False):
        pytest.skip("Flask not available")
    app_module.app.testing = True
    if getattr(app_module, "cfg", None) is not None:
        app_module.cfg.setdefault("auth", {})
        app_module.cfg["auth"]["enabled"] = False
    return app_module.app.test_client()


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (True, True),
        (False, False),
        ("true", True),
        ("TRUE", True),
        ("1", True),
        ("yes", True),
        ("t", True),
        ("false", False),
        ("False", False),
        ("0", False),
        ("no", False),
        ("f", False),
        (None, None),
        ("maybe", None),
        ("f.a.l.s.e", None),
        ("t.r.u.e", None),
        ("false!", None),
        ("-1", None),
        (" TRUE ", True),
    ],
)
def test_coerce_bool_is_strict_and_tri_state(value, expected):
    assert coerce_bool(value) is expected


@pytest.mark.parametrize(
    ("comment", "override", "expected"),
    [
        ("homekit=true", None, True),
        ("homekit=false", None, False),
        (None, None, False),
        ("homekit=true", True, True),
        ("homekit=true", False, False),
        ("homekit=false", True, True),
        ("homekit=false", False, False),
        ("homekit=true", "false", False),
        ("homekit=false", "1", True),
        ("homekit=true", "unbekannt", True),
        ("homekit=true", "f.a.l.s.e", True),
        ("homekit=false", "t.r.u.e", False),
    ],
)
def test_resolve_homekit_mode_prefers_explicit_override(comment, override, expected):
    project = {"info": {"comment": comment}} if comment else {"info": {}}
    general = {}
    if override is not None:
        general["homekit_enabled"] = override

    assert resolve_homekit_mode(project, general) is expected


def test_resolve_homekit_mode_without_general_config_uses_module_config():
    assert resolve_homekit_mode({"info": {"comment": "homekit=true"}}) is True


def _preview_module(**extra):
    return SimpleNamespace(
        create_building=lambda _: pytest.fail("prepared building should be reused"),
        get_addresses=lambda _: pytest.fail("prepared addresses should be reused"),
        put_addresses_in_building=lambda *_: pytest.fail("prepared house should be reused"),
        get_gateway_ip=lambda _: None,
        is_alexa_enabled=lambda _: False,
        **extra,
    )


def test_preview_prefers_generator_resolver_and_receives_saved_general():
    seen = {}

    def resolver(project, general):
        seen["general"] = general
        return False

    knx_module = _preview_module(
        is_homekit_enabled=lambda _: True,
        resolve_homekit_mode=resolver,
    )

    preview = build_project_preview(
        {"info": {"comment": "homekit=true"}},
        knx_module,
        parsed=(None, [], []),
        general_config={"homekit_enabled": False},
    )

    assert preview["metadata"]["homekit_enabled"] is False
    assert seen["general"] == {"homekit_enabled": False}


def test_preview_falls_back_to_ets_for_modules_without_resolver():
    knx_module = _preview_module(is_homekit_enabled=lambda _: True)

    preview = build_project_preview(
        {"info": {"comment": "homekit=false"}},
        knx_module,
        parsed=(None, [], []),
        general_config={"homekit_enabled": False},
    )

    assert preview["metadata"]["homekit_enabled"] is True


def test_config_round_trip_keeps_explicit_false_and_sibling_keys(client, monkeypatch):
    from web_ui.backend import app as app_module

    previous = {
        "output_format": "legacy",
        "general": {
            "central_function_keyword": "zentral",
            "homekit_rollershutter_sendUpDownForExtents": True,
        },
    }
    saved = []
    monkeypatch.setattr(app_module, "load_generator_config", lambda _root: deepcopy(previous))
    monkeypatch.setattr(
        app_module,
        "save_generator_config",
        lambda config, _root: saved.append(deepcopy(config)),
    )
    monkeypatch.setattr(
        app_module,
        "get_paths",
        lambda _root: SimpleNamespace(secrets_file=None),
    )

    new_config = deepcopy(previous)
    new_config["general"].update(
        {
            "homekit_enabled": False,
            "homekit_rollershutter_sendUpDownForExtents": False,
            "homekit_rollershutter_stop": True,
            "homekit_rollershutter_stopSameDirection": False,
        }
    )

    response = client.post("/api/config", json=new_config)

    assert response.status_code == 200
    assert len(saved) == 1
    general = saved[0]["general"]
    assert general["homekit_enabled"] is False
    assert general["homekit_rollershutter_sendUpDownForExtents"] is False
    assert general["homekit_rollershutter_stop"] is True
    assert general["homekit_rollershutter_stopSameDirection"] is False
    assert general["central_function_keyword"] == "zentral"
    assert knxproject_to_openhab.coerce_bool(general["homekit_enabled"]) is False
