"""Configuration tests for the issue #89 HomeKit preferences."""

import json
import sys
from pathlib import Path

import pytest

import ets_to_openhab
import knxproject_to_openhab
from config import config

ROOT = Path(__file__).resolve().parents[1]


def test_shipped_config_defines_homekit_blinds_defaults():
    shipped = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    general = shipped["general"]

    assert general["homekit_rollershutter_sendUpDownForExtents"] is True
    assert general["homekit_rollershutter_stop"] is False
    assert general["homekit_rollershutter_stopSameDirection"] is False
    # The tri-state override must stay absent so ETS detection remains the default.
    assert "homekit_enabled" not in general


@pytest.mark.parametrize(
    ("detected", "general", "expected"),
    [
        (True, {}, True),
        (False, {}, False),
        (False, {"homekit_enabled": True}, True),
        (True, {"homekit_enabled": False}, False),
        (True, {"homekit_enabled": None}, True),
        (False, {"homekit_enabled": "true"}, True),
        (True, {"homekit_enabled": "false"}, False),
        (False, {"homekit_enabled": 1}, True),
        (True, {"homekit_enabled": 0}, False),
    ],
)
def test_resolve_homekit_enabled_applies_tri_state_override(detected, general, expected):
    assert knxproject_to_openhab.resolve_homekit_enabled(detected, general) is expected


def test_resolve_homekit_enabled_handles_missing_general_configuration():
    assert knxproject_to_openhab.resolve_homekit_enabled(True, None) is True
    assert knxproject_to_openhab.resolve_homekit_enabled(False, None) is False


@pytest.mark.parametrize(
    ("detected_comment", "override", "expected"),
    [
        ("homekit=true", False, False),
        ("homekit=false", True, True),
        ("homekit=true", None, True),
        ("homekit=false", None, False),
        ("", None, False),
    ],
)
def test_cli_main_uses_same_homekit_resolution(
    monkeypatch, tmp_path, detected_comment, override, expected
):
    project = {"info": {"comment": detected_comment}}
    project_file = tmp_path / "project.json"
    project_file.write_text(json.dumps(project), encoding="utf-8")

    if override is None:
        monkeypatch.delitem(config["general"], "homekit_enabled", raising=False)
    else:
        monkeypatch.setitem(config["general"], "homekit_enabled", override)

    monkeypatch.setattr(ets_to_openhab, "floors", [])
    monkeypatch.setattr(ets_to_openhab, "all_addresses", [])
    monkeypatch.setattr(ets_to_openhab, "GWIP", None)
    monkeypatch.setattr(ets_to_openhab, "PRJ_NAME", "Demo")
    monkeypatch.setattr(ets_to_openhab, "B_HOMEKIT", False)
    monkeypatch.setattr(ets_to_openhab, "B_ALEXA", False)

    monkeypatch.setattr(knxproject_to_openhab, "create_building", lambda _project: [])
    monkeypatch.setattr(knxproject_to_openhab, "get_addresses", lambda _project: [])
    monkeypatch.setattr(
        knxproject_to_openhab,
        "put_addresses_in_building",
        lambda _building, _addresses, _project: [{"name_long": "Demo", "floors": []}],
    )
    monkeypatch.setattr(knxproject_to_openhab, "get_gateway_ip", lambda _project: None)
    monkeypatch.setattr(knxproject_to_openhab, "is_alexa_enabled", lambda _project: False)
    monkeypatch.setattr(ets_to_openhab, "main", lambda: None)
    monkeypatch.setattr(
        sys,
        "argv",
        ["knxproject_to_openhab.py", "--readDump", "--file_path", str(project_file)],
    )

    knxproject_to_openhab.main()

    assert ets_to_openhab.B_HOMEKIT is expected
