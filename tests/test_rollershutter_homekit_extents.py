"""Regression tests for HomeKit rollershutter extent metadata.

The tests generate a small anonymous project from scratch and inspect both the
legacy DSL and the native YAML model, so the equipment-group parameter scope is
covered instead of only the item metadata.
"""

import json
import re
from copy import deepcopy
from pathlib import Path

import pytest
import yaml

import ets_to_openhab
import knxproject_to_openhab
from config import config
from openhab_yaml import parse_metadata, render_yaml

KEY_EXTENTS = "homekit_rollershutter_sendUpDownForExtents"
KEY_STOP = "homekit_rollershutter_stop"
KEY_STOP_SAME_DIRECTION = "homekit_rollershutter_stopSameDirection"

GENERATOR_GLOBALS = (
    "floors",
    "all_addresses",
    "used_addresses",
    "equipments",
    "FENSTERKONTAKTE",
    "export_to_influx",
    "partial_dimmers",
    "partial_unknowns",
    "PRJ_NAME",
    "B_HOMEKIT",
    "B_ALEXA",
    "GWIP",
)


def _flags(*, write=False, read=False, transmit=False):
    return {
        "read": read,
        "write": write,
        "communication": True,
        "update": False,
        "read_on_init": False,
        "transmit": transmit,
    }


def _project():
    """Return an anonymous project with travel, stop, position and slats."""
    write = _flags(write=True)
    status = _flags(read=True, transmit=True)
    prefix = "[anon]@+RM1 Living (-M1)|Jalousie:"
    return {
        "info": {"name": "Blind Home", "comment": "homekit=true"},
        "locations": {
            "loc1": {
                "type": "Building",
                "name": "House",
                "description": "House",
                "spaces": {
                    "floor1": {
                        "type": "Floor",
                        "name": "=EG",
                        "description": "EG",
                        "spaces": {
                            "room1": {
                                "type": "Room",
                                "name": "+RM1",
                                "description": "Living",
                                "usage_text": "Living",
                                "devices": ["1.1.1"],
                            }
                        },
                    }
                },
            }
        },
        "group_ranges": {
            "1": {
                "name": "=EG",
                "group_ranges": {"1/2": {"name": "+RM1", "group_ranges": {}}},
            }
        },
        "devices": {
            "1.1.1": {
                "hardware_name": "KNX IP Interface",
                "description": "192.168.1.1",
                "communication_object_ids": [
                    "co_shutter",
                    "co_stop",
                    "co_position",
                    "co_position_status",
                    "co_lamella",
                    "co_lamella_status",
                ],
            }
        },
        "communication_objects": {
            "co_stop": {
                "name": "Shutter Stop",
                "number": 2,
                "text": "Jalousie",
                "function_text": "Lamellenverstellung / Stopp",
                "device_address": "1.1.1",
                "channel": "CH_JAL",
                "dpts": [{"main": 1, "sub": 10}],
                "flags": write,
                "group_address_links": ["1/2/2"],
            },
            "co_position": {
                "name": "Shutter Position",
                "number": 3,
                "text": "Jalousie",
                "function_text": "Absolute Position",
                "device_address": "1.1.1",
                "channel": "CH_JAL",
                "dpts": [{"main": 5, "sub": 1}],
                "flags": write,
                "group_address_links": ["1/2/3"],
            },
            "co_position_status": {
                "name": "Shutter Position Status",
                "number": 4,
                "text": "Jalousie",
                "function_text": "Status Absolute Position",
                "device_address": "1.1.1",
                "channel": "CH_JAL",
                "dpts": [{"main": 5, "sub": 1}],
                "flags": status,
                "group_address_links": ["1/2/4"],
            },
            "co_shutter": {
                "name": "Shutter",
                "number": 1,
                "text": "Jalousie",
                "function_text": "Jalousie Auf/Ab",
                "device_address": "1.1.1",
                "channel": "CH_JAL",
                "dpts": [{"main": 1, "sub": 8}],
                "flags": write,
                "group_address_links": ["1/2/1"],
                "device_communication_objects": [
                    {
                        "name": "Shutter Stop",
                        "number": 2,
                        "text": "Jalousie",
                        "function_text": "Lamellenverstellung / Stopp",
                        "channel": "CH_JAL",
                        "dpts": [{"main": 1, "sub": 10}],
                        "flags": write,
                        "group_address_links": ["1/2/2"],
                    },
                    {
                        "name": "Shutter Position",
                        "number": 3,
                        "text": "Jalousie",
                        "function_text": "Absolute Position",
                        "channel": "CH_JAL",
                        "dpts": [{"main": 5, "sub": 1}],
                        "flags": write,
                        "group_address_links": ["1/2/3"],
                    },
                    {
                        "name": "Shutter Position Status",
                        "number": 4,
                        "text": "Jalousie",
                        "function_text": "Status Absolute Position",
                        "channel": "CH_JAL",
                        "dpts": [{"main": 5, "sub": 1}],
                        "flags": status,
                        "group_address_links": ["1/2/4"],
                    },
                ],
            },
            "co_lamella": {
                "name": "Slat Position",
                "number": 10,
                "text": "Jalousie",
                "function_text": ":(Dimm Wert)",
                "device_address": "1.1.1",
                "channel": "CH_LAM",
                "dpts": [{"main": 5, "sub": 1}],
                "flags": write,
                "group_address_links": ["1/2/5"],
                "device_communication_objects": [
                    {
                        "name": "Slat Position Status",
                        "number": 11,
                        "text": "Jalousie",
                        "function_text": "Status Dimmwert",
                        "channel": "CH_LAM",
                        "dpts": [{"main": 5, "sub": 1}],
                        "flags": status,
                        "group_address_links": ["1/2/6"],
                    }
                ],
            },
            "co_lamella_status": {
                "name": "Slat Position Status",
                "number": 11,
                "text": "Jalousie",
                "function_text": "Status Dimmwert",
                "device_address": "1.1.1",
                "channel": "CH_LAM",
                "dpts": [{"main": 5, "sub": 1}],
                "flags": status,
                "group_address_links": ["1/2/6"],
            },
        },
        "group_addresses": {
            "ga_shutter": {
                "name": f"{prefix}(Jalousie Auf/Ab)",
                "address": "1/2/1",
                "description": "",
                "comment": "",
                "communication_object_ids": ["co_shutter"],
                "dpt": {"main": 1, "sub": 8},
            },
            "ga_stop": {
                "name": f"{prefix}(Lamellenverstellung/Stop)",
                "address": "1/2/2",
                "description": "",
                "comment": "",
                "communication_object_ids": ["co_shutter"],
                "dpt": {"main": 1, "sub": 10},
            },
            "ga_position": {
                "name": f"{prefix}(Absolute Position)",
                "address": "1/2/3",
                "description": "",
                "comment": "",
                "communication_object_ids": ["co_shutter"],
                "dpt": {"main": 5, "sub": 1},
            },
            "ga_position_status": {
                "name": f"{prefix}(Status Absolute Position)",
                "address": "1/2/4",
                "description": "",
                "comment": "",
                "communication_object_ids": ["co_shutter"],
                "dpt": {"main": 5, "sub": 1},
            },
            "ga_lamella": {
                "name": f"{prefix}(Absolute Lamellenposition)",
                "address": "1/2/5",
                "description": "",
                "comment": "",
                "communication_object_ids": ["co_lamella"],
                "dpt": {"main": 5, "sub": 1},
            },
            "ga_lamella_status": {
                "name": f"{prefix}(Status Absolute Lamellenposition)",
                "address": "1/2/6",
                "description": "",
                "comment": "",
                "communication_object_ids": ["co_lamella"],
                "dpt": {"main": 5, "sub": 1},
            },
        },
    }


def _generate(project, general):
    """Run the real generator while restoring every touched module global."""
    saved_general = deepcopy(config["general"])
    saved_globals = {name: getattr(ets_to_openhab, name) for name in GENERATOR_GLOBALS}
    try:
        config["general"] = deepcopy(general)
        building = knxproject_to_openhab.create_building(project)
        addresses = knxproject_to_openhab.get_addresses(project)
        house = knxproject_to_openhab.put_addresses_in_building(building, addresses, project)

        ets_to_openhab.floors = house[0]["floors"]
        ets_to_openhab.all_addresses = addresses
        ets_to_openhab.GWIP = knxproject_to_openhab.get_gateway_ip(project)
        ets_to_openhab.B_HOMEKIT = knxproject_to_openhab.resolve_homekit_mode(project, general)
        ets_to_openhab.B_ALEXA = knxproject_to_openhab.is_alexa_enabled(project)
        ets_to_openhab.PRJ_NAME = house[0]["name_long"]
        ets_to_openhab.used_addresses = []
        ets_to_openhab.equipments = {}
        ets_to_openhab.export_to_influx = []
        ets_to_openhab.partial_dimmers = []
        ets_to_openhab.partial_unknowns = []

        items, _sitemap, things, yaml_model = ets_to_openhab.gen_building(include_yaml_model=True)
        return items, things, yaml_model
    finally:
        config["general"] = saved_general
        for name, value in saved_globals.items():
            setattr(ets_to_openhab, name, value)


def _base_general():
    """Return a config without the optional HomeKit overrides.

    ``config.json`` may ship explicit defaults for the rollershutter options,
    so remove them to exercise the missing-key fallback that existing user
    configurations rely on.
    """
    general = deepcopy(config["general"])
    general.pop("homekit_enabled", None)
    general.pop("homekit_bridge_count", None)
    general.pop(KEY_EXTENTS, None)
    general.pop(KEY_STOP, None)
    general.pop(KEY_STOP_SAME_DIRECTION, None)
    return general


def _window_covering_group_line(items_text):
    lines = [
        line
        for line in items_text.splitlines()
        if line.startswith("Group") and 'homekit = "WindowCovering"' in line
    ]
    assert len(lines) == 1
    return lines[0]


def _group_options(line):
    matches = re.findall(r'homekit\s*=\s*"WindowCovering"\s*\[([^\]]*)\]', line)
    assert len(matches) == 1
    options = {}
    for part in matches[0].split(","):
        key, _, value = part.strip().partition("=")
        options[key] = value
    return options


def _yaml_window_covering_group(yaml_model):
    matches = [
        (name, item)
        for name, item in yaml_model["items"].items()
        if item.get("type") == "Group"
        and item.get("metadata", {}).get("homekit", {}).get("value") == "WindowCovering"
    ]
    assert len(matches) == 1
    return matches[0][1]


def _lamella_item_line(items_text):
    lines = [line for line in items_text.splitlines() if "CurrentHorizontalTiltAngle" in line]
    assert len(lines) == 1
    return lines[0]


def test_missing_extents_key_defaults_to_true_on_group_in_legacy_and_yaml():
    general = _base_general()
    assert KEY_EXTENTS not in general

    items, _things, yaml_model = _generate(_project(), general)

    line = _window_covering_group_line(items)
    options = _group_options(line)
    assert options["sendUpDownForExtents"] == "true"
    assert options["instance"] == "1"
    # Exactly one parameter block, so the instance bracket is not
    # duplicated by the new options.
    assert len(re.findall(r'homekit\s*=\s*"WindowCovering"\s*\[', line)) == 1

    yaml_group = _yaml_window_covering_group(yaml_model)
    assert yaml_group["metadata"]["homekit"]["config"] == {**options, "instance": 1}
    assert parse_metadata(
        f'homekit="WindowCovering" [{", ".join(f"{k}={v}" for k, v in options.items())}]'
    )["homekit"]["config"] == {**options, "instance": 1}


def test_explicit_false_removes_extents_but_keeps_instance():
    general = _base_general()
    general[KEY_EXTENTS] = False

    items, _things, yaml_model = _generate(_project(), general)

    options = _group_options(_window_covering_group_line(items))
    assert "sendUpDownForExtents" not in options
    assert options["instance"] == "1"
    assert _yaml_window_covering_group(yaml_model)["metadata"]["homekit"]["config"] == {
        **options,
        "instance": 1,
    }


@pytest.mark.parametrize(
    ("stop", "same_direction", "expected"),
    [
        (None, None, set()),
        (True, None, {"stop"}),
        (None, True, {"stopSameDirection"}),
        (True, True, {"stop", "stopSameDirection"}),
        (False, False, set()),
        ("true", "0", {"stop"}),
    ],
)
def test_stop_options_are_independent_and_optional(stop, same_direction, expected):
    general = _base_general()
    if stop is None:
        general.pop(KEY_STOP, None)
    else:
        general[KEY_STOP] = stop
    if same_direction is None:
        general.pop(KEY_STOP_SAME_DIRECTION, None)
    else:
        general[KEY_STOP_SAME_DIRECTION] = same_direction

    items, _things, _yaml_model = _generate(_project(), general)

    options = _group_options(_window_covering_group_line(items))
    enabled = {key for key in options if key in {"stop", "stopSameDirection"}}
    assert enabled == expected


def test_homekit_disabled_produces_no_homekit_metadata():
    general = _base_general()
    general["homekit_enabled"] = False

    items, things, yaml_model = _generate(_project(), general)

    assert "WindowCovering" not in items
    assert "sendUpDownForExtents" not in items
    assert "homekit" not in items
    assert "1/2/1" in things
    assert "1/2/2" in things
    assert all(
        item.get("metadata", {}).get("homekit") is None for item in yaml_model["items"].values()
    )


@pytest.mark.parametrize(
    ("override", "expected"),
    [
        (None, True),
        (True, True),
        (False, False),
        ("true", True),
        ("false", False),
        ("1", True),
        ("0", False),
    ],
)
def test_homekit_mode_uses_tri_state_override(override, expected):
    general = _base_general()
    if override is None:
        general.pop("homekit_enabled", None)
    else:
        general["homekit_enabled"] = override

    assert knxproject_to_openhab.resolve_homekit_mode(_project(), general) is expected


def test_things_keep_travel_stop_and_slat_characteristics():
    items, things, yaml_model = _generate(_project(), _base_general())

    assert "1/2/1" in things
    assert "1/2/2" in things
    lamella_line = _lamella_item_line(items)
    assert "CurrentHorizontalTiltAngle, TargetHorizontalTiltAngle" in lamella_line

    tilt_items = [
        (name, item)
        for name, item in yaml_model["items"].items()
        if item.get("metadata", {}).get("homekit", {}).get("value")
        == "CurrentHorizontalTiltAngle, TargetHorizontalTiltAngle"
    ]
    assert len(tilt_items) == 1
    assert "instance" not in tilt_items[0][1]["metadata"]["homekit"].get("config", {})


def _bridge_project(simple_count, complex_count=0):
    project = _project()
    project["communication_objects"] = {}
    project["group_addresses"] = {}
    for index in range(complex_count):
        original = _project()
        replacements = {f"1/2/{n}": f"2/{index // 40}/{index % 40 * 6 + n}" for n in range(1, 7)}
        replacements.update(
            {key: f"unit{index}_{key}" for key in original["communication_objects"]}
        )
        replacements["Living"] = f"Unit{index}"

        def clone(value):
            if isinstance(value, dict):
                return {replacements.get(k, k): clone(v) for k, v in value.items()}
            if isinstance(value, list):
                return [clone(v) for v in value]
            if isinstance(value, str):
                if value in replacements:
                    return replacements[value]
                return value.replace("Living", f"Unit{index}")
            return value

        project["communication_objects"].update(clone(original["communication_objects"]))
        project["group_addresses"].update(
            {f"unit{index}_{k}": clone(v) for k, v in original["group_addresses"].items()}
        )
    for index in range(simple_count):
        co_id = f"sensor{index}"
        address = f"3/{index // 250}/{index % 250}"
        project["communication_objects"][co_id] = {
            "device_address": "1.1.1",
            "dpts": [{"main": 1, "sub": 19}],
            "flags": _flags(read=True, transmit=True),
            "group_address_links": [address],
        }
        project["group_addresses"][co_id] = {
            "name": f"[anon]@+RM1 Living Sensor{index}",
            "address": address,
            "description": "",
            "comment": "",
            "communication_object_ids": [co_id],
            "dpt": {"main": 1, "sub": 19},
        }
    project["devices"]["1.1.1"]["communication_object_ids"] = list(project["communication_objects"])
    for ga in project["group_addresses"].values():
        main, middle, _ = ga["address"].split("/")
        top = project["group_ranges"].setdefault(main, {"name": "=EG", "group_ranges": {}})
        top["group_ranges"][f"{main}/{middle}"] = {"name": "+RM1", "group_ranges": {}}
    return project


def _bridge_roots(model):
    return [
        (name, item["metadata"]["homekit"]["config"]["instance"])
        for name, item in model["items"].items()
        if "instance" in item.get("metadata", {}).get("homekit", {}).get("config", {})
    ]


@pytest.mark.parametrize("count", [129, 130, 131, 261])
@pytest.mark.parametrize("bridge_count", [None, 1, 2, 3])
def test_bridge_assignment_counts_real_accessories(count, bridge_count, caplog):
    general = _base_general()
    if bridge_count is not None:
        general["homekit_bridge_count"] = bridge_count
    if bridge_count == 2 and count > 260:
        with pytest.raises(ValueError, match="HomeKit.*capacity"):
            _generate(_bridge_project(count), general)
        return
    items, _, model = _generate(_bridge_project(count), general)
    roots = _bridge_roots(model)
    assert len(roots) == count
    assert [instance for _, instance in roots] == [
        1 if bridge_count in (None, 1) else index // 130 + 1 for index in range(count)
    ]
    assert "Instance=" not in items
    assert len(re.findall(r"\binstance=\d+", items)) == count
    loaded = yaml.safe_load(render_yaml(model))
    assert _bridge_roots(loaded) == roots
    if count > 130 and bridge_count in (None, 1):
        assert "bridge 1" in caplog.text


def test_complex_accessories_cross_boundary_without_counting_characteristics():
    general = _base_general()
    general["homekit_bridge_count"] = 2
    items, _, model = _generate(_bridge_project(0, 131), general)
    roots = _bridge_roots(model)
    assert len(roots) == 131
    assert [instance for _, instance in roots] == [1] * 130 + [2]
    for name, item in model["items"].items():
        homekit = item.get("metadata", {}).get("homekit")
        if homekit and item["type"] != "Group":
            assert "instance" not in homekit.get("config", {})
            assert any(group in dict(roots) for group in item["groups"]), name
    assert len(re.findall(r"\binstance=\d+", items)) == 131
    assert "Instance=" not in items


def test_mixed_complex_and_simple_accessories_use_one_shared_counter():
    general = _base_general()
    general["homekit_bridge_count"] = 2
    _, _, model = _generate(_bridge_project(130, 2), general)
    roots = _bridge_roots(model)
    assert len(roots) == 132
    assert [instance for _, instance in roots] == [1] * 130 + [2] * 2
    assert len([name for name, _ in roots if name.startswith("equipment_")]) == 2


def test_thermostat_and_dimmer_roots_preserve_other_metadata():
    project = json.loads((Path(__file__).parent / "fixtures" / "mini_project.json").read_text())
    project["info"]["comment"] = "homekit=true"
    general = _base_general()
    general["homekit_bridge_count"] = 2
    items, _, model = _generate(project, general)
    roots = _bridge_roots(model)
    # A dimmer is one accessory despite its additional Brightness service.
    assert len(roots) == 3
    assert all(instance == 1 for _, instance in roots)
    assert 'OFF="4", HEAT="1", COOL="2"' in items
    thermostat_characteristic = next(
        item["metadata"]["homekit"]
        for item in model["items"].values()
        if "CurrentHeatingCoolingMode"
        in item.get("metadata", {}).get("homekit", {}).get("value", "")
    )
    assert thermostat_characteristic["config"] == {"OFF": "4", "HEAT": "1", "COOL": "2"}


@pytest.mark.parametrize("value", [0, -1, True, False, "2", 2.0, None, [], {}])
def test_invalid_bridge_count_stops_generation(value):
    general = _base_general()
    general["homekit_bridge_count"] = value
    with pytest.raises(ValueError, match="homekit_bridge_count"):
        _generate(_project(), general)
