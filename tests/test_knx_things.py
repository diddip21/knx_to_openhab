"""Tests for the shared KNX Things model and its DSL compatibility renderer."""

import json
from pathlib import Path

import yaml

import ets_to_openhab
import knxproject_to_openhab
from knx_things import (
    KnxChannel,
    KnxThingsModel,
    render_dsl_channels,
    render_inactive_dsl,
    render_inactive_yaml,
    render_yaml,
)


def test_render_dsl_channels_preserves_channel_configuration_order():
    model = KnxThingsModel(
        gateway_config={
            "type": "TUNNEL",
            "ipAddress": "192.168.1.1",
            "portNumber": 3671,
            "autoReconnectPeriod": 30,
        },
        channels=(
            KnxChannel(
                channel_id="i_living_light",
                channel_type="dimmer",
                label="Living Light",
                config={"position": "1/1/1+<1/1/2", "switch": "1/1/3"},
            ),
        ),
    )

    assert render_dsl_channels(model) == (
        'Type dimmer    :   i_living_light   "Living Light"   '
        '[ position="1/1/1+<1/1/2", switch="1/1/3" ]\n'
    )


def test_gen_building_model_contains_ets_gateway_and_typed_channels(monkeypatch):
    project_path = Path(__file__).parent / "fixtures" / "mini_project.json"
    project = json.loads(project_path.read_text(encoding="utf-8"))
    building = knxproject_to_openhab.create_building(project)
    addresses = knxproject_to_openhab.get_addresses(project)
    house = knxproject_to_openhab.put_addresses_in_building(building, addresses, project)

    monkeypatch.setattr(ets_to_openhab, "floors", house[0]["floors"])
    monkeypatch.setattr(ets_to_openhab, "all_addresses", addresses)
    monkeypatch.setattr(ets_to_openhab, "used_addresses", [])
    monkeypatch.setattr(ets_to_openhab, "equipments", {})
    monkeypatch.setattr(ets_to_openhab, "FENSTERKONTAKTE", [])
    monkeypatch.setattr(ets_to_openhab, "export_to_influx", [])
    monkeypatch.setattr(ets_to_openhab, "partial_dimmers", [])
    monkeypatch.setattr(ets_to_openhab, "partial_unknowns", [])
    monkeypatch.setattr(ets_to_openhab, "GWIP", "192.168.1.1")
    monkeypatch.setattr(ets_to_openhab, "B_HOMEKIT", False)
    monkeypatch.setattr(ets_to_openhab, "B_ALEXA", False)

    _, _, model = ets_to_openhab.gen_building_model()

    assert model.gateway_config == {
        "type": "TUNNEL",
        "ipAddress": "192.168.1.1",
        "portNumber": 3671,
        "autoReconnectPeriod": 30,
    }
    dimmer = next(
        channel for channel in model.channels if channel.channel_id.endswith("DimmenDimmWert")
    )
    assert dimmer.channel_type == "dimmer"
    assert dimmer.config["position"] == "1/1/1+<1/1/2"


def test_render_yaml_preserves_bridge_and_generic_channel_uids():
    model = KnxThingsModel(
        gateway_config={
            "type": "TUNNEL",
            "ipAddress": "192.168.1.1",
            "portNumber": 3671,
            "autoReconnectPeriod": 30,
        },
        channels=(
            KnxChannel(
                channel_id="i_living_light",
                channel_type="switch",
                label="Living Light",
                config={"ga": "1/1/1+<1/1/2"},
            ),
        ),
    )

    document = yaml.safe_load(render_yaml(model))

    assert document["version"] == 1
    assert document["things"]["knx:ip:bridge"] == {
        "isBridge": True,
        "config": {
            "type": "TUNNEL",
            "ipAddress": "192.168.1.1",
            "portNumber": 3671,
            "autoReconnectPeriod": 30,
        },
    }
    assert document["things"]["knx:device:bridge:generic"] == {
        "bridge": "knx:ip:bridge",
        "label": "KNX generic device",
        "channels": {
            "i_living_light": {
                "type": "switch",
                "label": "Living Light",
                "config": {"ga": "1/1/1+<1/1/2"},
            }
        },
    }


def test_render_yaml_preserves_ipv6_gateway_address():
    model = KnxThingsModel(
        gateway_config={"type": "TUNNEL", "ipAddress": "2001:db8::1"},
        channels=(),
    )

    document = yaml.safe_load(render_yaml(model))

    assert document["things"]["knx:ip:bridge"]["config"]["ipAddress"] == "2001:db8::1"


def test_render_yaml_supports_router_mode_without_ip_address():
    model = KnxThingsModel(
        gateway_config={"type": "ROUTER", "autoReconnectPeriod": 60},
        channels=(),
    )

    bridge = yaml.safe_load(render_yaml(model))["things"]["knx:ip:bridge"]

    assert bridge["isBridge"] is True
    assert bridge["config"] == {"type": "ROUTER", "autoReconnectPeriod": 60}


def test_render_yaml_emits_generic_device_with_empty_channel_mapping():
    model = KnxThingsModel(
        gateway_config={"type": "ROUTER"},
        channels=(),
    )

    document = yaml.safe_load(render_yaml(model))

    assert document["things"]["knx:device:bridge:generic"] == {
        "bridge": "knx:ip:bridge",
        "label": "KNX generic device",
        "channels": {},
    }


def test_inactive_outputs_are_valid_and_do_not_define_a_bridge():
    assert yaml.safe_load(render_inactive_yaml()) == {"version": 1}
    assert "Bridge knx:ip:bridge" not in render_inactive_dsl()


def test_export_output_writes_yaml_only_when_yaml_is_selected(tmp_path, monkeypatch):
    model = KnxThingsModel(
        gateway_config={"type": "TUNNEL", "ipAddress": "192.168.1.1"},
        channels=(KnxChannel("light", "switch", "Light", {"ga": "1/1/1"}),),
    )
    yaml_path = tmp_path / "yaml" / "knx.yaml"
    dsl_path = tmp_path / "things" / "knx.things"
    configuration = {
        "things_format": "yaml",
        "yaml_path": str(yaml_path),
        "things_path": str(dsl_path),
        "items_path": str(tmp_path / "items" / "knx.items"),
        "sitemaps_path": str(tmp_path / "sitemaps" / "knx.sitemap"),
        "influx_path": str(tmp_path / "persistence" / "knx.persist"),
        "fenster_path": str(tmp_path / "rules" / "fenster.rules"),
        "openhab_path": str(tmp_path),
    }
    monkeypatch.setattr(ets_to_openhab, "export_to_influx", [])
    monkeypatch.setattr(ets_to_openhab, "FENSTERKONTAKTE", [])
    monkeypatch.setattr(ets_to_openhab, "partial_dimmers", [])
    monkeypatch.setattr(ets_to_openhab, "partial_unknowns", [])

    ets_to_openhab.export_output("", "", model, configuration=configuration)

    assert yaml.safe_load(yaml_path.read_text(encoding="utf-8"))["version"] == 1
    assert not dsl_path.exists()


def test_export_output_keeps_structured_model_on_default_dsl_path(tmp_path, monkeypatch):
    model = KnxThingsModel(
        gateway_config={"type": "TUNNEL", "ipAddress": "192.168.1.1"},
        channels=(KnxChannel("light", "switch", "Light", {"ga": "1/1/1"}),),
    )
    dsl_path = tmp_path / "things" / "knx.things"
    configuration = {
        "things_path": str(dsl_path),
        "items_path": str(tmp_path / "items" / "knx.items"),
        "sitemaps_path": str(tmp_path / "sitemaps" / "knx.sitemap"),
        "influx_path": str(tmp_path / "persistence" / "knx.persist"),
        "fenster_path": str(tmp_path / "rules" / "fenster.rules"),
        "openhab_path": str(tmp_path),
    }
    monkeypatch.setattr(ets_to_openhab, "export_to_influx", [])
    monkeypatch.setattr(ets_to_openhab, "FENSTERKONTAKTE", [])
    monkeypatch.setattr(ets_to_openhab, "partial_dimmers", [])
    monkeypatch.setattr(ets_to_openhab, "partial_unknowns", [])

    ets_to_openhab.export_output("", "", model, configuration=configuration)

    content = dsl_path.read_text(encoding="utf-8")
    assert 'ipAddress="192.168.1.1"' in content
    assert 'Type switch    :   light   "Light"   [ ga="1/1/1" ]' in content
