import json
from pathlib import Path

import ets_to_openhab
import knxproject_to_openhab
from config import config

TESTS_DIR = Path(__file__).parent
MINI_PROJECT = TESTS_DIR / "fixtures" / "mini_project.json"


def _generate_from_project(project_path: Path, tmp_path: Path):
    with open(project_path, encoding="utf-8") as f:
        project = json.load(f)

    building = knxproject_to_openhab.create_building(project)
    addresses = knxproject_to_openhab.get_addresses(project)
    house = knxproject_to_openhab.put_addresses_in_building(building, addresses, project)

    ets_to_openhab.floors = house[0]["floors"]
    ets_to_openhab.all_addresses = addresses
    ets_to_openhab.GWIP = knxproject_to_openhab.get_gateway_ip(project)
    ets_to_openhab.B_HOMEKIT = knxproject_to_openhab.is_homekit_enabled(project)
    ets_to_openhab.B_ALEXA = knxproject_to_openhab.is_alexa_enabled(project)
    ets_to_openhab.PRJ_NAME = house[0]["name_long"]

    items, sitemap, things = ets_to_openhab.gen_building()

    original_paths = {
        "items_path": config["items_path"],
        "things_path": config["things_path"],
        "sitemaps_path": config["sitemaps_path"],
        "influx_path": config["influx_path"],
    }

    config["items_path"] = str(tmp_path / "knx.items")
    config["things_path"] = str(tmp_path / "knx.things")
    config["sitemaps_path"] = str(tmp_path / "knx.sitemap")
    config["influx_path"] = str(tmp_path / "influxdb.persist")

    ets_to_openhab.export_output(items, sitemap, things)

    for key, value in original_paths.items():
        config[key] = value

    return tmp_path


def test_mini_things_contains_expected_entries(tmp_path):
    output_dir = _generate_from_project(MINI_PROJECT, tmp_path)
    things = (output_dir / "knx.things").read_text(encoding="utf-8")

    assert "Type dimmer" in things
    assert "Type rollershutter" in things
    assert "Type number" in things
    assert "1/1/1+<1/1/2" in things
    assert 'upDown="1/2/1"' in things


def test_mini_items_contains_expected_entries(tmp_path):
    output_dir = _generate_from_project(MINI_PROJECT, tmp_path)
    items = (output_dir / "knx.items").read_text(encoding="utf-8")

    assert "Dimmer   i_EG_RM1_DimmenDimmWert" in items
    assert "Rollershutter   i_EG_RM1_JalousieJalousieAufAb" in items
    assert "Number   i_EG_RM1_HeizenBetriebsartvorwahl" in items


def test_mini_sitemap_contains_expected_entries(tmp_path):
    output_dir = _generate_from_project(MINI_PROJECT, tmp_path)
    sitemap = (output_dir / "knx.sitemap").read_text(encoding="utf-8")

    assert 'Frame label="=EG"' in sitemap
    assert "Default item=i_EG_RM1_DimmenDimmWert" in sitemap
    assert "Default item=i_EG_RM1_JalousieJalousieAufAb" in sitemap
    assert "Default item=i_EG_RM1_HeizenBetriebsartvorwahl" in sitemap
