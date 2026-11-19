"""Regression tests for HomeKit window-covering metadata (issue #89).

The effective HomeKit configuration for a grouped ``WindowCovering`` accessory
lives on the generated equipment group.  These tests cover the documented
default (``sendUpDownForExtents=true``), an explicit opt-out, the independent
optional stop switches, lamella metadata and HomeKit-disabled output.
"""

import copy
import json
import re
from pathlib import Path

import pytest
import yaml

import ets_to_openhab
import knxproject_to_openhab
from config import config
from openhab_yaml import parse_metadata

TESTS_DIR = Path(__file__).parent
MINI_PROJECT = TESTS_DIR / "fixtures" / "mini_project.json"

ROLLER_EQUIPMENT = "equipment_i_EG_RM1_JalousieJalousieAufAb"
ROLLER_ITEM = "i_EG_RM1_JalousieJalousieAufAb"
LAMELLA_ITEM = "i_EG_RM1_JalousieAbsoluteLamellenposition"


def _load_project():
    with open(MINI_PROJECT, encoding="utf-8") as project_file:
        return json.load(project_file)


def _project_with_lamella():
    """Add a DPT 5.001 lamella control/status pair to the mini project."""
    project = copy.deepcopy(_load_project())
    project["info"]["comment"] = "homekit=true"
    project["devices"]["1.1.1"]["communication_object_ids"].append("co_lamella")
    project["communication_objects"]["co_lamella"] = {
        "name": "Lamella",
        "number": 40,
        "text": "Lamella",
        "function_text": ":(Absolute Lamellenposition)",
        "description": "",
        "device_address": "1.1.1",
        "channel": "CH4",
        "dpts": [{"main": 5, "sub": 1}],
        "flags": {
            "read": False,
            "write": True,
            "communication": True,
            "update": False,
            "read_on_init": False,
        },
        "group_address_links": ["1/2/4"],
        "device_communication_objects": [
            {
                "name": "Lamella Status",
                "number": 41,
                "text": "Lamella",
                "function_text": "Status akt. Lamellenposition",
                "channel": "CH4",
                "dpts": [{"main": 5, "sub": 1}],
                "flags": {
                    "read": True,
                    "write": False,
                    "transmit": True,
                    "update": False,
                },
                "group_address_links": ["1/2/5"],
            }
        ],
    }
    project["group_addresses"]["ga_lamella"] = {
        "name": "=EG +RM1 Jalousie:(Absolute Lamellenposition)",
        "address": "1/2/4",
        "description": "",
        "comment": "",
        "communication_object_ids": ["co_lamella"],
        "dpt": {"main": 5, "sub": 1},
    }
    project["group_addresses"]["ga_lamella_status"] = {
        "name": "=EG +RM1 Jalousie:Status akt. Lamellenposition",
        "address": "1/2/5",
        "description": "",
        "comment": "",
        "communication_object_ids": ["co_lamella"],
        "dpt": {"main": 5, "sub": 1},
    }
    return project


def _reset_generator():
    ets_to_openhab.floors = []
    ets_to_openhab.all_addresses = []
    ets_to_openhab.used_addresses = []
    ets_to_openhab.export_to_influx = []
    ets_to_openhab.equipments = {}
    ets_to_openhab.FENSTERKONTAKTE = []
    ets_to_openhab.partial_dimmers = []
    ets_to_openhab.partial_unknowns = []
    ets_to_openhab.GWIP = None
    ets_to_openhab.PRJ_NAME = "HomeKit blinds"
    ets_to_openhab.B_ALEXA = False


def _set_general(monkeypatch, homekit_enabled, send_up_down, stop, stop_same):
    """Apply the generator settings, including the tri-state HomeKit override."""
    if homekit_enabled is None:
        monkeypatch.delitem(config["general"], "homekit_enabled", raising=False)
    else:
        monkeypatch.setitem(config["general"], "homekit_enabled", homekit_enabled)

    settings = {
        "homekit_rollershutter_sendUpDownForExtents": send_up_down,
        "homekit_rollershutter_stop": stop,
        "homekit_rollershutter_stopSameDirection": stop_same,
    }
    for key, value in settings.items():
        if value is None:
            monkeypatch.delitem(config["general"], key, raising=False)
        else:
            monkeypatch.setitem(config["general"], key, value)


def _generate(
    monkeypatch,
    *,
    project=None,
    homekit_enabled=True,  # Fixture has no ETS HomeKit flag; enable it for HomeKit cases.
    send_up_down=True,
    stop=False,
    stop_same=False,
):
    project = project or _load_project()
    _reset_generator()
    _set_general(monkeypatch, homekit_enabled, send_up_down, stop, stop_same)

    building = knxproject_to_openhab.create_building(project)
    addresses = knxproject_to_openhab.get_addresses(project)
    house = knxproject_to_openhab.put_addresses_in_building(building, addresses, project)

    ets_to_openhab.floors = house[0]["floors"]
    ets_to_openhab.all_addresses = addresses
    ets_to_openhab.GWIP = knxproject_to_openhab.get_gateway_ip(project)
    ets_to_openhab.B_HOMEKIT = knxproject_to_openhab.resolve_homekit_enabled(
        knxproject_to_openhab.is_homekit_enabled(project), config.get("general")
    )
    ets_to_openhab.B_ALEXA = knxproject_to_openhab.is_alexa_enabled(project)
    ets_to_openhab.PRJ_NAME = house[0]["name_long"]

    return ets_to_openhab.gen_building(include_yaml_model=True)


def _equipment_line(items):
    for line in items.splitlines():
        if line.startswith(f"Group   {ROLLER_EQUIPMENT} "):
            return line
    pytest.fail(f"missing roller shutter equipment group: {ROLLER_EQUIPMENT}")


def _item_line(items, item_name):
    for line in items.splitlines():
        if line.startswith(f"Rollershutter   {item_name} "):
            return line
    pytest.fail(f"missing roller shutter item: {item_name}")


def _homekit_config(metadata):
    return metadata["homekit"].get("config", {})


def test_missing_extents_key_defaults_to_true(monkeypatch):
    items, _sitemap, _things, model = _generate(monkeypatch, send_up_down=None)

    equipment_line = _equipment_line(items)
    expected = r'homekit = "WindowCovering" \[Instance=\d+, sendUpDownForExtents="true"\]'
    assert re.search(expected, equipment_line)

    item_line = _item_line(items, ROLLER_ITEM)
    assert re.search(r"\[Instance=\d+\]", item_line)
    assert "sendUpDownForExtents" not in item_line

    equipment_metadata = model["items"][ROLLER_EQUIPMENT]["metadata"]
    assert equipment_metadata["homekit"]["value"] == "WindowCovering"
    equipment_config = _homekit_config(equipment_metadata)
    assert equipment_config["sendUpDownForExtents"] == "true"
    assert set(equipment_config) == {"Instance", "sendUpDownForExtents"}

    item_config = _homekit_config(model["items"][ROLLER_ITEM]["metadata"])
    assert set(item_config) == {"Instance"}


def test_explicit_extents_false_is_preserved(monkeypatch):
    items, _sitemap, _things, model = _generate(monkeypatch, send_up_down=False)

    equipment_line = _equipment_line(items)
    assert re.search(r'homekit = "WindowCovering" \[Instance=\d+\]', equipment_line)
    assert "sendUpDownForExtents" not in equipment_line
    assert "] [" not in equipment_line

    equipment_config = _homekit_config(model["items"][ROLLER_EQUIPMENT]["metadata"])
    assert set(equipment_config) == {"Instance"}


@pytest.mark.parametrize(
    ("stop", "stop_same", "expected_options"),
    [
        (True, False, ['stop="true"']),
        (False, True, ['stopSameDirection="true"']),
        (True, True, ['stop="true"', 'stopSameDirection="true"']),
    ],
)
def test_optional_stop_switches_are_independent(monkeypatch, stop, stop_same, expected_options):
    items, _sitemap, _things, model = _generate(
        monkeypatch, send_up_down=False, stop=stop, stop_same=stop_same
    )

    equipment_line = _equipment_line(items)
    options = re.search(r'homekit = "WindowCovering" \[([^]]+)\]', equipment_line)
    assert options
    option_text = options.group(1)
    assert option_text.startswith("Instance=")
    for expected in expected_options:
        assert expected in option_text
    if not stop:
        assert "stop=" not in option_text
    if not stop_same:
        assert "stopSameDirection" not in option_text

    equipment_config = _homekit_config(model["items"][ROLLER_EQUIPMENT]["metadata"])
    for expected in expected_options:
        key, _separator, value = expected.partition("=")
        assert equipment_config[key] == value.strip('"')


def test_stop_switches_are_absent_by_default(monkeypatch):
    items, _sitemap, _things, model = _generate(monkeypatch, send_up_down=None)

    equipment_line = _equipment_line(items)
    assert "stop=" not in equipment_line
    assert "stopSameDirection" not in equipment_line

    equipment_config = _homekit_config(model["items"][ROLLER_EQUIPMENT]["metadata"])
    assert set(equipment_config) == {"Instance", "sendUpDownForExtents"}


def test_lamella_metadata_is_retained_next_to_the_covering_options(monkeypatch):
    _items, _sitemap, _things, model = _generate(
        monkeypatch, project=_project_with_lamella(), send_up_down=None
    )

    assert LAMELLA_ITEM in model["items"]
    lamella_metadata = model["items"][LAMELLA_ITEM]["metadata"]["homekit"]
    assert lamella_metadata["value"] == "CurrentHorizontalTiltAngle, TargetHorizontalTiltAngle"
    assert set(lamella_metadata.get("config", {})) == {"Instance"}
    assert "sendUpDownForExtents" not in lamella_metadata.get("config", {})

    equipment_config = _homekit_config(model["items"][ROLLER_EQUIPMENT]["metadata"])
    assert equipment_config["sendUpDownForExtents"] == "true"


@pytest.mark.parametrize("homekit_enabled", [False, None])
def test_homekit_disabled_leaves_legacy_rollershutter_output_unchanged(
    monkeypatch, homekit_enabled
):
    project = _load_project()
    project["info"]["comment"] = "homekit=false"
    items, _sitemap, _things, model = _generate(
        monkeypatch, project=project, homekit_enabled=homekit_enabled
    )

    equipment_line = _equipment_line(items)
    item_line = _item_line(items, ROLLER_ITEM)
    assert "homekit" not in equipment_line
    assert "homekit" not in item_line
    assert "WindowCovering" not in items

    assert "metadata" not in model["items"][ROLLER_EQUIPMENT]
    assert "metadata" not in model["items"][ROLLER_ITEM]


def test_homekit_override_enables_covering_metadata_without_ets_comment(monkeypatch):
    project = _load_project()
    items, _sitemap, _things, model = _generate(
        monkeypatch, project=project, homekit_enabled=True, send_up_down=None
    )

    equipment_line = _equipment_line(items)
    assert "homekit" in equipment_line
    assert "sendUpDownForExtents" in equipment_line
    assert model["items"][ROLLER_EQUIPMENT]["metadata"]["homekit"]["value"] == "WindowCovering"


@pytest.mark.parametrize(
    ("homekit_enabled", "send_up_down", "stop", "stop_same"),
    [
        (True, None, False, False),
        (True, False, False, False),
        (True, True, True, True),
        (False, None, True, True),
    ],
)
def test_exported_legacy_and_yaml_have_equivalent_homekit_metadata(
    monkeypatch, tmp_path, homekit_enabled, send_up_down, stop, stop_same
):
    items, sitemap, things, model = _generate(
        monkeypatch,
        project=_project_with_lamella(),
        homekit_enabled=homekit_enabled,
        send_up_down=send_up_down,
        stop=stop,
        stop_same=stop_same,
    )
    cfg = copy.deepcopy(config)
    cfg.update(
        {
            "output_format": "legacy",
            "openhab_path": str(tmp_path),
            "items_path": str(tmp_path / "items/knx.items"),
            "things_path": str(tmp_path / "things/knx.things"),
            "sitemaps_path": str(tmp_path / "sitemaps/knx.sitemap"),
            "influx_path": str(tmp_path / "persistence/influxdb.persist"),
            "fenster_path": str(tmp_path / "rules/fenster.rules"),
            "yaml_path": str(tmp_path / "yaml/knx.yaml"),
        }
    )
    ets_to_openhab.export_output(
        items,
        sitemap,
        things,
        configuration=cfg,
        yaml_model=model,
        include_private_persistence=False,
    )
    legacy = Path(cfg["items_path"]).read_text(encoding="utf-8")
    group_line = _equipment_line(legacy)
    item_line = _item_line(legacy, ROLLER_ITEM)
    lamella_line = next(
        line
        for line in legacy.splitlines()
        if re.match(rf"^\S+\s+{re.escape(LAMELLA_ITEM)}\s", line)
    )

    cfg["output_format"] = "yaml"
    ets_to_openhab.export_output(
        items,
        sitemap,
        things,
        configuration=cfg,
        yaml_model=model,
        include_private_persistence=False,
    )
    exported_yaml = yaml.safe_load(Path(cfg["yaml_path"]).read_text(encoding="utf-8"))
    for name, line in (
        (ROLLER_EQUIPMENT, group_line),
        (ROLLER_ITEM, item_line),
        (LAMELLA_ITEM, lamella_line),
    ):
        legacy_metadata = parse_metadata(line.partition("{")[2].rpartition("}")[0])
        yaml_metadata = exported_yaml["items"][name].get("metadata", {})
        assert legacy_metadata.get("homekit") == yaml_metadata.get("homekit")
        if homekit_enabled:
            assert "Instance" in yaml_metadata["homekit"]["config"]
        else:
            assert "homekit" not in yaml_metadata
    if homekit_enabled:
        lamella_metadata = exported_yaml["items"][LAMELLA_ITEM]["metadata"]["homekit"]
        assert lamella_metadata["value"] == "CurrentHorizontalTiltAngle, TargetHorizontalTiltAngle"
        assert set(lamella_metadata["config"]) == {"Instance"}
        options = exported_yaml["items"][ROLLER_EQUIPMENT]["metadata"]["homekit"]["config"]
        assert ("sendUpDownForExtents" in options) is (send_up_down is not False)
        assert ("stop" in options) is stop
        assert ("stopSameDirection" in options) is stop_same
