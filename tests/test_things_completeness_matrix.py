import json
from pathlib import Path

import ets_to_openhab
import knxproject_to_openhab
from config import config
from completeness import check_completeness

TESTS_DIR = Path(__file__).parent
PROJECTS = [
    TESTS_DIR / "fixtures" / "mini_project.json",
    TESTS_DIR / "Charne.knxproj.json",
    TESTS_DIR / "upload.knxprojarchive.json",
]


def _generate_things(project_path: Path, tmp_path: Path) -> str:
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

    return (tmp_path / "knx.things").read_text(encoding="utf-8")


def _rule_checks_for_project(project_path: Path, tmp_path: Path):
    things_text = _generate_things(project_path, tmp_path)
    return check_completeness(things_text)


def test_things_completeness_matrix_all_projects(tmp_path):
    missing_required = []
    recommended_missing = []

    for project_path in PROJECTS:
        project_missing, project_recommended = _rule_checks_for_project(
            project_path, tmp_path
        )
        missing_required.extend(project_missing)
        recommended_missing.extend(project_recommended)

    if recommended_missing:
        print("Recommended (not required) feedback missing:")
        for kind, reason, line in recommended_missing:
            print(f" - {kind}: {reason} :: {line}")

    assert missing_required == []
