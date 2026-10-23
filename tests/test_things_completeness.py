import re
from pathlib import Path

TESTS_DIR = Path(__file__).parent
MINI_PROJECT = TESTS_DIR / "fixtures" / "mini_project.json"

PARAM_KV = re.compile(r"(\w+)=\"([^\"]+)\"")


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


def test_things_completeness_mini_fixture(tmp_path, generate_output_from_json):
    output_dir = generate_output_from_json(MINI_PROJECT, tmp_path)
    things_text = (output_dir / "knx.things").read_text(encoding="utf-8")
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
