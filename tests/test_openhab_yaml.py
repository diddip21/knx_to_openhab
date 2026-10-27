import copy
import json
from pathlib import Path

import pytest
import yaml

import ets_to_openhab
import knxproject_to_openhab
from config import config
from openhab_yaml import (
    YamlModelValidationError,
    add_channel,
    add_item,
    new_model,
    parse_metadata,
    parse_visibility,
    render_yaml,
    validate_model,
)

MINI_PROJECT = Path(__file__).parent / "fixtures" / "mini_project.json"
SYNTHETIC_YAML_GOLDEN = Path(__file__).parent / "fixtures" / "synthetic_openhab_5_2.yaml"
YAML_CASES = [
    Path(__file__).parent / "Charne.knxproj.json",
    Path(__file__).parent / "upload.knxprojarchive.json",
    MINI_PROJECT,
]


def _yaml_generation(project_path=MINI_PROJECT):
    with open(project_path, encoding="utf-8") as file:
        project = json.load(file)

    building = knxproject_to_openhab.create_building(project)
    addresses = knxproject_to_openhab.get_addresses(project)
    house = knxproject_to_openhab.put_addresses_in_building(building, addresses, project)

    ets_to_openhab.floors = house[0]["floors"]
    ets_to_openhab.all_addresses = addresses
    ets_to_openhab.GWIP = knxproject_to_openhab.get_gateway_ip(project)
    ets_to_openhab.B_HOMEKIT = knxproject_to_openhab.is_homekit_enabled(project)
    ets_to_openhab.B_ALEXA = knxproject_to_openhab.is_alexa_enabled(project)
    ets_to_openhab.PRJ_NAME = house[0]["name_long"]
    ets_to_openhab.equipments = {}
    ets_to_openhab.used_addresses = []
    ets_to_openhab.export_to_influx = []
    ets_to_openhab.FENSTERKONTAKTE = []

    return ets_to_openhab.gen_building(include_yaml_model=True)


def _mini_yaml_model():
    return _yaml_generation()[3]


def _synthetic_yaml_model():
    model = new_model("Example Home", "192.0.2.1", "Example")
    add_item(
        model,
        "ExampleRoom",
        {
            "type": "Group",
            "label": "Example Room",
            "groups": ["Base"],
            "tags": ["Room"],
        },
    )
    channel_uid = add_channel(
        model,
        "ExampleDimmer",
        "dimmer",
        "Example dimmer",
        {"position": "0/0/1+<0/0/2"},
    )
    add_item(
        model,
        "ExampleDimmer",
        {
            "type": "Dimmer",
            "label": "Example Dimmer",
            "groups": ["ExampleRoom"],
            "tags": ["Light"],
            "channel": channel_uid,
        },
    )
    model["sitemaps"]["knx"]["widgets"].append(
        {"type": "Default", "item": "ExampleDimmer", "label": "Example Dimmer"}
    )
    return model


def test_mini_project_generates_native_openhab_52_model():
    model = _mini_yaml_model()

    validate_model(model)
    assert model["version"] == 1
    assert model["things"]["knx:ip:bridge"]["isBridge"] is True

    channels = model["things"]["knx:device:bridge:generic"]["channels"]
    assert channels["i_EG_RM1_DimmenDimmWert"]["type"] == "dimmer"
    assert channels["i_EG_RM1_DimmenDimmWert"]["config"] == {
        "position": "1/1/1+<1/1/2",
        "switch": "1/1/3",
    }
    assert channels["i_EG_RM1_JalousieJalousieAufAb"]["config"] == {
        "upDown": "1/2/1",
        "stopMove": "1/2/2",
        "position": "1/2/3",
    }

    items = model["items"]
    dimmer = items["i_EG_RM1_DimmenDimmWert"]
    assert dimmer["type"] == "Dimmer"
    assert dimmer["groups"] == ["equipment_i_EG_RM1_DimmenDimmWert"]
    assert dimmer["channel"] == ("knx:device:bridge:generic:i_EG_RM1_DimmenDimmWert")

    sitemap = model["sitemaps"]["knx"]
    assert sitemap["widgets"][0]["type"] == "Frame"
    assert sitemap["widgets"][0]["widgets"][0]["item"] == "map1_1"
    assert sitemap["widgets"][0]["widgets"][0]["widgets"][0]["type"] == "Default"


@pytest.mark.parametrize("project_path", YAML_CASES, ids=lambda path: path.stem)
def test_yaml_model_preserves_generated_entity_counts(project_path):
    items_text, sitemap_text, things_text, model = _yaml_generation(project_path)

    validate_model(model)
    assert len(model["things"]["knx:device:bridge:generic"]["channels"]) == things_text.count(
        "Type "
    )
    assert (
        len(model["items"]) == len([line for line in items_text.splitlines() if line.strip()]) + 1
    )  # Base comes from items.template in legacy output.

    yaml_leaf_widgets = [
        widget
        for frame in model["sitemaps"]["knx"]["widgets"]
        for room in frame.get("widgets", [])
        for widget in room.get("widgets", [])
    ]
    legacy_leaf_widgets = sum(
        1
        for line in sitemap_text.splitlines()
        if line.strip().startswith(("Default item=", "Selection item="))
    )
    assert len(yaml_leaf_widgets) == legacy_leaf_widgets


def test_yaml_renderer_quotes_boolean_like_openhab_strings():
    text = render_yaml(_mini_yaml_model())

    assert yaml.safe_load(text) == _mini_yaml_model()
    assert "version: 1" in text
    assert "isBridge: true" in text
    assert 'type: "TUNNEL"' in text
    assert 'ga: "20.102:1/3/1+<1/3/2"' in text


def test_synthetic_yaml_matches_reviewable_golden_file():
    assert render_yaml(_synthetic_yaml_model()) == SYNTHETIC_YAML_GOLDEN.read_text(encoding="utf-8")


def test_yaml_export_is_mutually_exclusive_with_legacy_model_files(tmp_path):
    model = _mini_yaml_model()
    cfg = copy.deepcopy(config)
    cfg.update(
        {
            "output_format": "yaml",
            "yaml_path": str(tmp_path / "yaml" / "knx.yaml"),
            "items_path": str(tmp_path / "items" / "knx.items"),
            "things_path": str(tmp_path / "things" / "knx.things"),
            "sitemaps_path": str(tmp_path / "sitemaps" / "knx.sitemap"),
            "influx_path": str(tmp_path / "persistence" / "influxdb.persist"),
            "fenster_path": str(tmp_path / "rules" / "fenster.rules"),
            "openhab_path": str(tmp_path),
        }
    )

    ets_to_openhab.export_output("", "", "", configuration=cfg, yaml_model=model)

    assert (tmp_path / "yaml" / "knx.yaml").is_file()
    assert not (tmp_path / "items" / "knx.items").exists()
    assert not (tmp_path / "things" / "knx.things").exists()
    assert not (tmp_path / "sitemaps" / "knx.sitemap").exists()
    assert (tmp_path / "persistence" / "influxdb.persist").is_file()
    assert (tmp_path / "rules" / "fenster.rules").is_file()


def test_yaml_export_retires_existing_legacy_model_files(tmp_path):
    model = _mini_yaml_model()
    cfg = copy.deepcopy(config)
    paths = {
        "items_path": tmp_path / "items" / "knx.items",
        "things_path": tmp_path / "things" / "knx.things",
        "sitemaps_path": tmp_path / "sitemaps" / "knx.sitemap",
    }
    for path in paths.values():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("stale legacy model", encoding="utf-8")
    cfg.update(
        {
            "output_format": "yaml",
            "yaml_path": str(tmp_path / "yaml" / "knx.yaml"),
            **{key: str(path) for key, path in paths.items()},
            "influx_path": str(tmp_path / "persistence" / "influxdb.persist"),
            "fenster_path": str(tmp_path / "rules" / "fenster.rules"),
            "openhab_path": str(tmp_path),
        }
    )

    ets_to_openhab.export_output("", "", "", configuration=cfg, yaml_model=model)

    assert (tmp_path / "yaml" / "knx.yaml").is_file()
    assert all(path.read_text(encoding="utf-8") == "" for path in paths.values())


def test_legacy_export_retires_existing_yaml_model_file(tmp_path):
    cfg = copy.deepcopy(config)
    yaml_path = tmp_path / "yaml" / "knx.yaml"
    yaml_path.parent.mkdir(parents=True)
    yaml_path.write_text("stale YAML model", encoding="utf-8")
    cfg.update(
        {
            "output_format": "legacy",
            "yaml_path": str(yaml_path),
            "items_path": str(tmp_path / "items" / "knx.items"),
            "things_path": str(tmp_path / "things" / "knx.things"),
            "sitemaps_path": str(tmp_path / "sitemaps" / "knx.sitemap"),
            "influx_path": str(tmp_path / "persistence" / "influxdb.persist"),
            "fenster_path": str(tmp_path / "rules" / "fenster.rules"),
            "openhab_path": str(tmp_path),
        }
    )

    ets_to_openhab.export_output("items", "sitemap", "things", configuration=cfg)

    assert yaml_path.read_text(encoding="utf-8") == ""
    assert all(
        (tmp_path / directory / filename).is_file()
        for directory, filename in (
            ("items", "knx.items"),
            ("things", "knx.things"),
            ("sitemaps", "knx.sitemap"),
        )
    )


def test_metadata_conversion_preserves_value_and_configuration():
    assert parse_metadata(
        ', stateDescription=""[options="1=Comfort,2=Standby"], alexa="Switch"'
    ) == {
        "stateDescription": {
            "value": "",
            "config": {"options": "1=Comfort,2=Standby"},
        },
        "alexa": {"value": "Switch"},
    }


def test_metadata_conversion_preserves_unquoted_homekit_instance():
    assert parse_metadata(', homekit="Switchable" [Instance=2]') == {
        "homekit": {"value": "Switchable", "config": {"Instance": "2"}}
    }


def test_visibility_uses_openhab_52_rule_and_condition_dtos():
    assert parse_visibility("visibility=[extended_view==ON]") == [
        {"conditions": [{"item": "extended_view", "condition": "==", "value": "ON"}]}
    ]


def test_visibility_preserves_non_default_condition_operator():
    assert parse_visibility("visibility=[temperature>=18]") == [
        {"conditions": [{"item": "temperature", "condition": ">=", "value": "18"}]}
    ]


def test_generated_debug_visibility_uses_openhab_52_sitemap_schema(tmp_path):
    project = json.loads(MINI_PROJECT.read_text(encoding="utf-8"))
    project["locations"]["loc1"]["spaces"]["floor1"]["spaces"]["room1"][
        "description"
    ] = "Living;debug"
    project_path = tmp_path / "debug-project.json"
    project_path.write_text(json.dumps(project), encoding="utf-8")

    model = _yaml_generation(project_path)[3]
    room_widget = model["sitemaps"]["knx"]["widgets"][0]["widgets"][0]
    serialized_widget = yaml.safe_load(render_yaml(model))["sitemaps"]["knx"]["widgets"][0][
        "widgets"
    ][0]

    expected_rules = [{"conditions": [{"item": "extended_view", "condition": "==", "value": "ON"}]}]
    assert room_widget["visibilityRules"] == expected_rules
    assert "visibility" not in room_widget
    assert serialized_widget["visibilityRules"] == expected_rules


def test_model_validation_rejects_orphaned_groups():
    model = _mini_yaml_model()
    model["items"]["i_EG_RM1_DimmenDimmWert"]["groups"] = ["MissingGroup"]

    with pytest.raises(YamlModelValidationError, match="MissingGroup"):
        validate_model(model)
