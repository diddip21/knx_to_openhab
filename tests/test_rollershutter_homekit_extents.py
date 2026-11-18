"""Regression tests for HomeKit rollershutter extent metadata.

The tests generate a small anonymous project from scratch and inspect both the
legacy DSL and the native YAML model, so the equipment-group parameter scope is
covered instead of only the item metadata.
"""

import re
from copy import deepcopy

import pytest

import ets_to_openhab
import knxproject_to_openhab
from config import config
from openhab_yaml import parse_metadata

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
    general = deepcopy(config["general"])
    general.pop("homekit_enabled", None)
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
    assert options["Instance"] == "1"
    # Exactly one parameter block, so the previous Instance-only bracket is not
    # duplicated by the new options.
    assert len(re.findall(r'homekit\s*=\s*"WindowCovering"\s*\[', line)) == 1

    yaml_group = _yaml_window_covering_group(yaml_model)
    assert yaml_group["metadata"]["homekit"]["config"] == options
    assert (
        parse_metadata(
            f'homekit="WindowCovering" [{", ".join(f"{k}={v}" for k, v in options.items())}]'
        )["homekit"]["config"]
        == options
    )


def test_explicit_false_removes_extents_but_keeps_instance():
    general = _base_general()
    general[KEY_EXTENTS] = False

    items, _things, yaml_model = _generate(_project(), general)

    options = _group_options(_window_covering_group_line(items))
    assert "sendUpDownForExtents" not in options
    assert options["Instance"] == "1"
    assert _yaml_window_covering_group(yaml_model)["metadata"]["homekit"]["config"] == options


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
    assert tilt_items[0][1]["metadata"]["homekit"]["config"]["Instance"] == "1"
