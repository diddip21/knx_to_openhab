import json
from pathlib import Path

import pytest

import ets_to_openhab
import knxproject_to_openhab
from config import config

TESTS_DIR = Path(__file__).parent
UPLOAD_PROJECT = TESTS_DIR / "upload.knxprojarchive.json"


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


@pytest.mark.parametrize(
    "needle",
    [
        "Rollershutter   i_UG_RM3_xxxRechtsM1RolladenRolladenAufAb",
        "Dimmer   i_EG_RM1_xxxSpotsFlurH18DimmenDimmWert",
        "Dimmer   i_EG_RM1_xxxFlurGarderobeWCM20HeizenStatusStellwert",
    ],
)
def test_items_contains_expected_patterns(tmp_path, needle):
    output_dir = _generate_from_project(UPLOAD_PROJECT, tmp_path)
    items_path = output_dir / "knx.items"
    content = items_path.read_text(encoding="utf-8")
    assert needle in content


@pytest.mark.parametrize(
    "needle",
    [
        "Bridge knx:ip:bridge",
        "Type rollershutter    :   i_UG_RM3_xxxRechtsM1RolladenRolladenAufAb",
        "Type dimmer    :   i_EG_RM1_xxxSpotsFlurH18DimmenDimmWert",
    ],
)
def test_things_contains_expected_patterns(tmp_path, needle):
    output_dir = _generate_from_project(UPLOAD_PROJECT, tmp_path)
    things_path = output_dir / "knx.things"
    content = things_path.read_text(encoding="utf-8")
    assert needle in content


@pytest.mark.parametrize(
    "needle",
    [
        'sitemap knx label="MiCasa"',
        "Default item=i_UG_RM3_xxxRechtsM1RolladenRolladenAufAb",
        "Default item=i_EG_RM1_xxxSpotsFlurH18DimmenDimmWert",
    ],
)
def test_sitemap_contains_expected_patterns(tmp_path, needle):
    output_dir = _generate_from_project(UPLOAD_PROJECT, tmp_path)
    sitemap_path = output_dir / "knx.sitemap"
    content = sitemap_path.read_text(encoding="utf-8")
    assert needle in content


def test_persistence_contains_strategy_block(tmp_path):
    output_dir = _generate_from_project(UPLOAD_PROJECT, tmp_path)
    persist_path = output_dir / "influxdb.persist"
    content = persist_path.read_text(encoding="utf-8")
    assert "Strategies" in content
    assert "Items" in content
