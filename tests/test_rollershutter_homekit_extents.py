"""Regression tests for the HomeKit WindowCovering end-position behaviour.

Issue #89: a configured slat (Lamellen) position in HomeKit drove the blind
fully up and out of its end position. The generator therefore emits
``sendUpDownForExtents=true`` on the WindowCovering equipment-group metadata so
0 %/100 % commands are translated to UP/DOWN and the actuator can perform its
own end-position slat correction.
"""

import copy

import ets_to_openhab
import knxproject_to_openhab
import openhab_yaml
from config import config

KEY_EXTENTS = "homekit_rollershutter_sendUpDownForExtents"
KEY_STOP = "homekit_rollershutter_stop"
KEY_STOP_SAME_DIRECTION = "homekit_rollershutter_stopSameDirection"

WINDOWCOVERING = 'homekit = "WindowCovering"'
TILT_HOMEKIT = 'homekit = "CurrentHorizontalTiltAngle, TargetHorizontalTiltAngle"'
POSITION_HOMEKIT = 'homekit = "CurrentPosition, TargetPosition, PositionState"'


def _synthetic_project(comment="homekit=true"):
    """Minimal synthetic blind project: up/down, stop/slat, position and tilt.

    Contains no private ETS data; the group names follow the generic
    ``=Floor +Room Device:(Function)`` style used by the generator.
    """
    return {
        "info": {
            "name": "Synthetic Blinds",
            "group_address_style": "ThreeLevel",
            "schema_version": "20",
            "language_code": "de-DE",
            "comment": comment,
        },
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
                "group_ranges": {"1/1": {"name": "+RM1", "group_ranges": {}}},
            }
        },
        "devices": {
            "1.1.1": {
                "hardware_name": "Blinds Actuator",
                "description": "",
                "communication_object_ids": ["co_blinds", "co_tilt"],
            }
        },
        "communication_objects": {
            "co_blinds": {
                "name": "Blinds",
                "number": 10,
                "text": "Blinds",
                "function_text": "Jalousie Auf/Ab",
                "description": "",
                "device_address": "1.1.1",
                "channel": "CH1",
                "dpts": [{"main": 1, "sub": 8}],
                "flags": {
                    "read": False,
                    "write": True,
                    "communication": True,
                    "update": False,
                    "read_on_init": False,
                },
                "group_address_links": ["1/1/1"],
                "device_communication_objects": [
                    {
                        "name": "Blinds Stop/Lamellen",
                        "number": 11,
                        "text": "Blinds",
                        "function_text": "Stop/Lamellen",
                        "channel": "CH1",
                        "dpts": [{"main": 1, "sub": 10}],
                        "flags": {
                            "read": False,
                            "write": True,
                            "transmit": False,
                            "update": False,
                        },
                        "group_address_links": ["1/1/2"],
                    },
                    {
                        "name": "Blinds Absolute Position",
                        "number": 12,
                        "text": "Blinds",
                        "function_text": "absolute Position",
                        "channel": "CH1",
                        "dpts": [{"main": 5, "sub": 1}],
                        "flags": {
                            "read": False,
                            "write": True,
                            "transmit": False,
                            "update": False,
                        },
                        "group_address_links": ["1/1/3"],
                    },
                    {
                        "name": "Blinds Status Position",
                        "number": 13,
                        "text": "Blinds",
                        "function_text": "Status Absolute Position",
                        "channel": "CH1",
                        "dpts": [{"main": 5, "sub": 1}],
                        "flags": {
                            "read": True,
                            "write": False,
                            "transmit": True,
                            "update": False,
                        },
                        "group_address_links": ["1/1/4"],
                    },
                ],
            },
            "co_tilt": {
                "name": "Tilt",
                "number": 20,
                "text": "Blinds",
                "function_text": "Absolute Lamellenposition",
                "description": "",
                "device_address": "1.1.1",
                "channel": "CH2",
                "dpts": [{"main": 5, "sub": 1}],
                "flags": {
                    "read": False,
                    "write": True,
                    "communication": True,
                    "update": False,
                    "read_on_init": False,
                },
                "group_address_links": ["1/2/1"],
                "device_communication_objects": [
                    {
                        "name": "Tilt Status",
                        "number": 21,
                        "text": "Blinds",
                        "function_text": "Status Absolute Lamellenposition",
                        "channel": "CH2",
                        "dpts": [{"main": 5, "sub": 1}],
                        "flags": {
                            "read": True,
                            "write": False,
                            "transmit": True,
                            "update": False,
                        },
                        "group_address_links": ["1/2/2"],
                    }
                ],
            },
        },
        "group_addresses": {
            "ga_blinds": {
                "name": "=EG +RM1 Jalousie:(Jalousie Auf/Ab)",
                "address": "1/1/1",
                "description": "",
                "comment": "",
                "communication_object_ids": ["co_blinds"],
                "dpt": {"main": 1, "sub": 8},
            },
            "ga_blinds_stop": {
                "name": "=EG +RM1 Jalousie:(Stop/Lamellen)",
                "address": "1/1/2",
                "description": "",
                "comment": "",
                "communication_object_ids": ["co_blinds"],
                "dpt": {"main": 1, "sub": 10},
            },
            "ga_blinds_pos": {
                "name": "=EG +RM1 Jalousie:(absolute Position)",
                "address": "1/1/3",
                "description": "",
                "comment": "",
                "communication_object_ids": ["co_blinds"],
                "dpt": {"main": 5, "sub": 1},
            },
            "ga_blinds_status": {
                "name": "=EG +RM1 Jalousie:(Status Absolute Position)",
                "address": "1/1/4",
                "description": "",
                "comment": "",
                "communication_object_ids": ["co_blinds"],
                "dpt": {"main": 5, "sub": 1},
            },
            "ga_tilt": {
                "name": "=EG +RM1 Jalousie:(Absolute Lamellenposition)",
                "address": "1/2/1",
                "description": "",
                "comment": "",
                "communication_object_ids": ["co_tilt"],
                "dpt": {"main": 5, "sub": 1},
            },
            "ga_tilt_status": {
                "name": "=EG +RM1 Jalousie:(Status Absolute Lamellenposition)",
                "address": "1/2/2",
                "description": "",
                "comment": "",
                "communication_object_ids": ["co_tilt"],
                "dpt": {"main": 5, "sub": 1},
            },
        },
    }


def _generate(project, general=None):
    """Run the generator over the synthetic project.

    Returns the legacy items text, the things text and the structured YAML
    model. The ``general`` mapping is applied to the shared generator config
    for the generation only and restored afterwards.
    """
    building = knxproject_to_openhab.create_building(project)
    addresses = knxproject_to_openhab.get_addresses(project)
    house = knxproject_to_openhab.put_addresses_in_building(building, addresses, project)

    ets_to_openhab.floors = house[0]["floors"]
    ets_to_openhab.all_addresses = addresses
    ets_to_openhab.used_addresses = []
    ets_to_openhab.equipments = {}
    ets_to_openhab.FENSTERKONTAKTE = []
    ets_to_openhab.export_to_influx = []
    ets_to_openhab.partial_dimmers = []
    ets_to_openhab.partial_unknowns = []
    ets_to_openhab.GWIP = "192.0.2.10"
    ets_to_openhab.B_HOMEKIT = knxproject_to_openhab.is_homekit_enabled(project)
    ets_to_openhab.B_ALEXA = knxproject_to_openhab.is_alexa_enabled(project)
    ets_to_openhab.PRJ_NAME = house[0]["name_long"]

    original_general = copy.deepcopy(config.get("general", {}))
    try:
        if general is not None:
            config["general"] = general
        items, _sitemap, things, yaml_model = ets_to_openhab.gen_building(
            include_yaml_model=True
        )
    finally:
        config["general"] = original_general

    openhab_yaml.validate_model(yaml_model)
    return items, things, yaml_model


def _windowcovering_group_lines(items_text):
    """Legacy lines of the equipment group carrying the WindowCovering metadata."""
    return [
        line
        for line in items_text.splitlines()
        if line.startswith("Group") and WINDOWCOVERING in line
    ]


def _group_metadata_fragment(line):
    """The ``{ ... }`` metadata fragment of a generated legacy group line."""
    left = line.find("{")
    right = line.rfind("}")
    assert left != -1 and right > left, f"group line without metadata: {line}"
    return line[left : right + 1]


def _items_with_homekit_value(yaml_model, value):
    return [
        item
        for item in yaml_model["items"].values()
        if isinstance(item, dict)
        and (item.get("metadata") or {}).get("homekit", {}).get("value") == value
    ]


def _single(items_text, yaml_model):
    """Assert exactly one WindowCovering group exists in both outputs."""
    group_lines = _windowcovering_group_lines(items_text)
    assert len(group_lines) == 1, items_text
    yaml_groups = _items_with_homekit_value(yaml_model, "WindowCovering")
    assert len(yaml_groups) == 1
    return group_lines[0], yaml_groups[0]


def test_missing_key_emits_send_up_down_for_extents_on_group_metadata():
    """Case A: without any key the default ``true`` reaches the group metadata."""
    items, things, yaml_model = _generate(_synthetic_project())

    group_line, yaml_group = _single(items, yaml_model)
    fragment = _group_metadata_fragment(group_line)

    # Exactly one valid parameter bracket carrying the default and the instance.
    assert fragment.count("[") == 1, fragment
    assert WINDOWCOVERING in fragment
    assert "sendUpDownForExtents=true" in fragment
    assert fragment.count("sendUpDownForExtents") == 1
    assert "Instance=1" in fragment
    roller_items = [
        item
        for item in yaml_model["items"].values()
        if isinstance(item, dict) and item.get("type") == "Rollershutter"
    ]
    assert len(roller_items) == 1
    roller_meta = roller_items[0]["metadata"]["homekit"]
    assert roller_meta["value"] == "CurrentPosition, TargetPosition, PositionState"
    assert "sendUpDownForExtents" not in roller_meta.get("config", {})

    # The generated Thing keeps the combined position/stop channels.
    assert 'upDown="1/1/1"' in things
    assert 'stopMove="1/1/2"' in things
    assert 'position="1/1/3+<1/1/4"' in things

    # Legacy and parsed YAML metadata agree semantically.
    legacy_meta = openhab_yaml.parse_metadata(fragment)
    assert legacy_meta["homekit"]["value"] == "WindowCovering"
    assert legacy_meta["homekit"]["config"]["sendUpDownForExtents"] == "true"
    assert legacy_meta["homekit"]["config"]["Instance"] == "1"
    assert yaml_group["metadata"] == legacy_meta


def test_explicit_false_removes_parameter_but_keeps_instance():
    """Case B: an explicit ``false`` suppresses the parameter, Instance stays."""
    items, things, yaml_model = _generate(_synthetic_project(), general={KEY_EXTENTS: False})

    group_line, yaml_group = _single(items, yaml_model)
    fragment = _group_metadata_fragment(group_line)

    assert fragment.count("[") == 1, fragment
    assert "sendUpDownForExtents" not in fragment
    assert "Instance=1" in fragment
    assert yaml_group["metadata"]["homekit"]["config"] == {"Instance": "1"}


def test_stop_options_are_independent_and_off_by_default():
    """Case C: stop/stopSameDirection appear only when explicitly enabled."""
    items, things, yaml_model = _generate(_synthetic_project(), general={KEY_EXTENTS: False})
    fragment = _group_metadata_fragment(_windowcovering_group_lines(items)[0])
    assert "stop=true" not in fragment
    assert "stopSameDirection=true" not in fragment

    items, things, yaml_model = _generate(
        _synthetic_project(),
        general={KEY_EXTENTS: False, KEY_STOP: True},
    )
    group_line, yaml_group = _single(items, yaml_model)
    fragment = _group_metadata_fragment(group_line)
    assert fragment.count("[") == 1, fragment
    assert "stop=true" in fragment
    assert "stopSameDirection=true" not in fragment
    assert "sendUpDownForExtents" not in fragment
    assert yaml_group["metadata"]["homekit"]["config"]["stop"] == "true"

    items, things, yaml_model = _generate(
        _synthetic_project(),
        general={KEY_STOP_SAME_DIRECTION: True},
    )
    group_line, _yaml_group = _single(items, yaml_model)
    fragment = _group_metadata_fragment(group_line)
    assert fragment.count("[") == 1, fragment
    assert "stopSameDirection=true" in fragment
    assert "stop=true" not in fragment
    assert "sendUpDownForExtents=true" in fragment

    items, things, yaml_model = _generate(
        _synthetic_project(),
        general={KEY_STOP: True, KEY_STOP_SAME_DIRECTION: True},
    )
    group_line, _yaml_group = _single(items, yaml_model)
    fragment = _group_metadata_fragment(group_line)
    assert fragment.count("[") == 1, fragment
    assert "stop=true" in fragment
    assert "stopSameDirection=true" in fragment
    assert "sendUpDownForExtents=true" in fragment


def test_homekit_disabled_output_has_no_homekit_metadata():
    """Case D: with HomeKit off nothing of the metadata is emitted."""
    items, yaml_model = _generate(_synthetic_project(comment="homekit=false"))

    assert "homekit" not in items
    assert _items_with_homekit_value(yaml_model, "WindowCovering") == []
    assert not any(
        item.get("metadata", {}).get("homekit")
        for item in yaml_model["items"].values()
        if isinstance(item, dict)
    )


def test_string_boolean_values_are_evaluated_strictly():
    """Case E: the string "false" must not count as enabled."""
    items, _yaml_model = _generate(_synthetic_project(), general={KEY_EXTENTS: "false"})
    fragment = _group_metadata_fragment(_windowcovering_group_lines(items)[0])
    assert "sendUpDownForExtents" not in fragment
    assert "Instance=1" in fragment

    items, _yaml_model = _generate(_synthetic_project(), general={KEY_EXTENTS: "true"})
    fragment = _group_metadata_fragment(_windowcovering_group_lines(items)[0])
    assert "sendUpDownForExtents=true" in fragment


def test_tilt_metadata_survives_in_legacy_and_yaml():
    """Case F: slat position keeps its HomeKit tilt characteristics."""
    items, yaml_model = _generate(_synthetic_project())

    assert TILT_HOMEKIT in items
    tilt_items = _items_with_homekit_value(
        yaml_model, "CurrentHorizontalTiltAngle, TargetHorizontalTiltAngle"
    )
    assert len(tilt_items) == 1
    tilt_meta = tilt_items[0]["metadata"]["homekit"]
    assert tilt_meta["config"]["Instance"] == "1"

    # The absolute position/tilt group addresses remain in the generated Thing.
    assert 'position="1/1/3+<1/1/4"' in items
    assert 'upDown="1/1/1"' in items
    assert 'stopMove="1/1/2"' in items
