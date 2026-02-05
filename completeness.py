import re
from typing import Dict, Iterable, List, Tuple

PARAM_KV = re.compile(r'(\w+)="([^"]+)"')

RULES: Dict[str, dict] = {
    "dimmer": {
        "required": ["position"],
        "one_of": [],
        "recommend_one_of": [["switch", "increaseDecrease"]],
        "recommend_status": False,
    },
    "rollershutter": {
        "required": ["upDown"],
        "one_of": [],
        "recommend_one_of": [["stopMove", "position"]],
        "recommend_status": False,
    },
    "switch": {
        "required": ["ga"],
        "one_of": [],
        "recommend_one_of": [],
        "recommend_status": True,
    },
    "number": {
        "required": ["ga"],
        "one_of": [],
        "recommend_one_of": [],
        "recommend_status": True,
    },
    "string": {
        "required": ["ga"],
        "one_of": [],
        "recommend_one_of": [],
        "recommend_status": False,
    },
    "datetime": {
        "required": ["ga"],
        "one_of": [],
        "recommend_one_of": [],
        "recommend_status": False,
    },
}


def iter_thing_lines(things_text: str) -> Iterable[str]:
    for line in things_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("Type ") and "[" in stripped and "]" in stripped:
            yield stripped


def parse_params(line: str) -> dict:
    left = line.rfind("[")
    right = line.rfind("]")
    if left == -1 or right == -1 or right < left:
        return {}
    params_str = line[left + 1 : right]
    return {m.group(1): m.group(2) for m in PARAM_KV.finditer(params_str)}


def thing_kind(line: str) -> str:
    return line.split()[1].strip()


def _has_status(ga_value: str) -> bool:
    return "+<" in ga_value if ga_value else False


def check_completeness(
    things_text: str,
) -> Tuple[List[Tuple[str, str, str]], List[Tuple[str, str, str]]]:
    missing_required: List[Tuple[str, str, str]] = []
    recommended_missing: List[Tuple[str, str, str]] = []

    for line in iter_thing_lines(things_text):
        kind = thing_kind(line)
        rule = RULES.get(kind)
        if not rule:
            continue

        params = parse_params(line)

        for key in rule.get("required", []):
            if key not in params:
                missing_required.append((kind, key, line))

        for group in rule.get("one_of", []):
            if not any(key in params for key in group):
                missing_required.append((kind, "one_of:" + "/".join(group), line))

        for group in rule.get("recommend_one_of", []):
            if not any(key in params for key in group):
                recommended_missing.append((kind, "one_of:" + "/".join(group), line))

        ga_value = params.get("ga", "")
        has_status = _has_status(ga_value)

        if rule.get("recommend_status") and ga_value and not has_status:
            recommended_missing.append((kind, "status_feedback", line))

        if (
            kind == "number"
            and ga_value
            and "20.102" in ga_value
            and not has_status
            and not rule.get("recommend_status")
        ):
            recommended_missing.append((kind, "status_feedback", line))

    return missing_required, recommended_missing
