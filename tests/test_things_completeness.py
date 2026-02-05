import json
import re
from pathlib import Path

import ets_to_openhab
import knxproject_to_openhab
from config import config

TESTS_DIR = Path(__file__).parent
MINI_PROJECT = TESTS_DIR / "fixtures" / "mini_project.json"

PARAM_KV = re.compile(r"(\w+)=\"([^\"]+)\"")


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


def _iter_thing_lines(things_text: str):
    for line in things_text.splitlines():
        if line.strip().startswith("Type ") and "[" in line and "]" in line:
            yield line.strip()


def _parse_params(line: str) -> dict:
    left = line.rfind("[")
    right = line.rfind("]")
    if left == -1 or right == -1 or right < left:
        return {}
    params_str = line[left + 1 : right]
    return {m.group(1): m.group(2) for m in PARAM_KV.finditer(params_str)}


def _thing_kind(line: str) -> str:
    # "Type dimmer : id ..."
    return line.split()[1].strip()


def test_things_completeness_mini_fixture(tmp_path):
    things_text = _generate_things(MINI_PROJECT, tmp_path)
    incomplete = []

    for line in _iter_thing_lines(things_text):
        kind = _thing_kind(line)
        params = _parse_params(line)

        if kind == "rollershutter":
            if "upDown" not in params or "position" not in params:
                incomplete.append((kind, line))
        elif kind == "dimmer":
            if "position" not in params or (
                "switch" not in params and "increaseDecrease" not in params
            ):
                incomplete.append((kind, line))
        elif kind == "number":
            if "ga" in params and "20.102" in params["ga"] and "+<" not in params["ga"]:
                incomplete.append((kind, line))

    assert incomplete == []
