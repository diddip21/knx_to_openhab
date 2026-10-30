"""Tests for the shared KNX Things model and its DSL compatibility renderer."""

import json
from pathlib import Path

import ets_to_openhab
import knxproject_to_openhab
from knx_things import KnxChannel, KnxThingsModel, render_dsl_channels


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
