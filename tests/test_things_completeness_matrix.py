import json
import re
from pathlib import Path

import ets_to_openhab
import knxproject_to_openhab
from config import config

TESTS_DIR = Path(__file__).parent
PROJECTS = [
    TESTS_DIR / "fixtures" / "mini_project.json",
    TESTS_DIR / "Charne.knxproj.json",
    TESTS_DIR / "upload.knxprojarchive.json",
]

PARAM_KV = re.compile(r"(\w+)=\"([^\"]+)\"")


class Rule:
    def __init__(
        self,
        required=None,
        one_of=None,
        recommend_one_of=None,
        recommend_status=False,
    ):
        self.required = required or []
        self.one_of = one_of or []
        self.recommend_one_of = recommend_one_of or []
        self.recommend_status = recommend_status


RULES = {
    "dimmer": Rule(required=["position"], recommend_one_of=[["switch", "increaseDecrease"]]),
    "rollershutter": Rule(
        required=["upDown"], recommend_one_of=[["stopMove", "position"]]
    ),
    "switch": Rule(required=["ga"], recommend_status=True),
    "number": Rule(required=["ga"], recommend_status=True),
    "string": Rule(required=["ga"]),
    "datetime": Rule(required=["ga"]),
}


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
    return line.split()[1].strip()


def _has_status(ga_value: str) -> bool:
    return "+<" in ga_value if ga_value else False


def _rule_checks_for_project(project_path: Path, tmp_path: Path):
    things_text = _generate_things(project_path, tmp_path)
    missing_required = []
    recommended_missing = []

    for line in _iter_thing_lines(things_text):
        kind = _thing_kind(line)
        rule = RULES.get(kind)
        if not rule:
            continue

        params = _parse_params(line)

        for key in rule.required:
            if key not in params:
                missing_required.append((kind, key, line))

        for group in rule.one_of:
            if not any(key in params for key in group):
                missing_required.append((kind, "one_of:" + "/".join(group), line))

        for group in rule.recommend_one_of:
            if not any(key in params for key in group):
                recommended_missing.append((kind, "one_of:" + "/".join(group), line))

        if rule.recommend_status and "ga" in params and not _has_status(params["ga"]):
            recommended_missing.append((kind, "status_feedback", line))

        if kind == "number" and "ga" in params and "20.102" in params["ga"]:
            if not _has_status(params["ga"]):
                recommended_missing.append((kind, "status_feedback", line))

    return missing_required, recommended_missing


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
