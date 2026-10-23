"""Structured openHAB 5.2 YAML model generation and validation.

The openHAB YAML format is a versioned, modular configuration format.  This
module deliberately works with Python mappings instead of converting complete
legacy DSL files.  The small parsing helpers only translate the generator's
existing metadata/config fragments at the point where those fragments are
created.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable, Mapping

OPENHAB_YAML_VERSION = 1
KNX_BRIDGE_UID = "knx:ip:bridge"
KNX_DEVICE_UID = "knx:device:bridge:generic"

_ASSIGNMENT = re.compile(r'(\w+)\s*=\s*"([^"]*)"\s*(?:\[\s*([^]]*)\s*\])?')
_ITEM_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SITEMAP_NAME = re.compile(r"^[A-Za-z0-9_]+$")
_PLAIN_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_.:-]*$")
_VISIBILITY = re.compile(
    r"visibility=\[\s*([A-Za-z_][A-Za-z0-9_]*)\s*(==|!=|<=|>=|<|>)\s*([^]]+)\s*\]"
)


class YamlModelValidationError(ValueError):
    """Raised when a generated model cannot be loaded safely by openHAB."""


def new_model(project_name: str, gateway_ip: str | None, sitemap_label: str) -> dict[str, Any]:
    """Create the fixed openHAB/KNX model roots used by the generator."""
    bridge_config: dict[str, Any] = {
        "type": "TUNNEL" if gateway_ip else "ROUTER",
        "autoReconnectPeriod": 30 if gateway_ip else 60,
    }
    if gateway_ip:
        bridge_config["ipAddress"] = gateway_ip
        bridge_config["portNumber"] = 3671

    return {
        "version": OPENHAB_YAML_VERSION,
        "things": {
            KNX_BRIDGE_UID: {
                "isBridge": True,
                "config": bridge_config,
            },
            KNX_DEVICE_UID: {
                "bridge": KNX_BRIDGE_UID,
                "channels": {},
            },
        },
        "items": {
            "Base": {
                "type": "Group",
                "label": project_name,
                "icon": "house",
                "tags": ["Location"],
            }
        },
        "sitemaps": {
            "knx": {
                "label": sitemap_label,
                "widgets": [],
            }
        },
    }


def parse_assignments(fragment: str) -> dict[str, str]:
    """Parse the key/value subset emitted for KNX channel configuration."""
    return {match.group(1): match.group(2) for match in _ASSIGNMENT.finditer(fragment)}


def parse_metadata(*fragments: str) -> dict[str, dict[str, Any]]:
    """Translate generated openHAB DSL metadata fragments to YAML metadata maps."""
    metadata: dict[str, dict[str, Any]] = {}
    for fragment in fragments:
        for match in _ASSIGNMENT.finditer(fragment or ""):
            namespace, value, config_fragment = match.groups()
            entry: dict[str, Any] = {"value": value}
            if config_fragment:
                entry["config"] = parse_assignments(config_fragment)
            metadata[namespace] = entry
    return metadata


def parse_tags(fragment: str) -> list[str]:
    """Return quoted tags from the generator's legacy tag fragment."""
    return [tag for tag in re.findall(r'"([^"]*)"', fragment or "") if tag]


def parse_item_type(item_type: str) -> dict[str, str]:
    """Split DSL dimension syntax (for example Number:Temperature)."""
    base_type, separator, dimension = item_type.partition(":")
    result = {"type": base_type}
    if separator and base_type.casefold() == "number":
        result["dimension"] = dimension
    return result


def normalize_icon(icon: str | None) -> str | None:
    """Convert DSL icon brackets to the plain YAML icon name."""
    if not icon:
        return None
    return icon.removeprefix("<").removesuffix(">") or None


def parse_visibility(fragment: str) -> dict[str, str] | None:
    """Convert the simple sitemap visibility expression emitted by this project."""
    match = _VISIBILITY.search(fragment or "")
    if not match:
        return None
    item, operator, argument = match.groups()
    return {"item": item, "operator": operator, "argument": argument.strip()}


def add_item(model: dict[str, Any], name: str, item: Mapping[str, Any]) -> None:
    """Add one Item while failing early on duplicate generated names."""
    items = model["items"]
    if name in items:
        raise YamlModelValidationError(f'duplicate generated Item name "{name}"')
    items[name] = {key: value for key, value in item.items() if value not in (None, [], {})}


def add_channel(
    model: dict[str, Any], channel_id: str, channel_type: str, label: str, config: Mapping[str, Any]
) -> str:
    """Add a custom KNX channel and return its complete channel UID."""
    channels = model["things"][KNX_DEVICE_UID]["channels"]
    if channel_id in channels:
        raise YamlModelValidationError(f'duplicate generated KNX channel "{channel_id}"')
    channels[channel_id] = {
        "type": channel_type,
        "label": label,
        "config": dict(config),
    }
    return f"{KNX_DEVICE_UID}:{channel_id}"


def _iter_sitemap_widgets(widgets: Iterable[Mapping[str, Any]]) -> Iterable[Mapping[str, Any]]:
    for widget in widgets:
        yield widget
        yield from _iter_sitemap_widgets(widget.get("widgets", []))


def validate_model(model: Mapping[str, Any]) -> None:
    """Validate cross-references and openHAB 5.2 model constraints."""
    errors: list[str] = []
    if model.get("version") != OPENHAB_YAML_VERSION:
        errors.append("top-level version must be 1")

    things = model.get("things")
    items = model.get("items")
    sitemaps = model.get("sitemaps")
    if not isinstance(things, Mapping):
        errors.append("things must be a map")
        things = {}
    if not isinstance(items, Mapping):
        errors.append("items must be a map")
        items = {}
    if not isinstance(sitemaps, Mapping):
        errors.append("sitemaps must be a map")
        sitemaps = {}

    group_names = {
        name
        for name, item in items.items()
        if isinstance(item, Mapping) and item.get("type") == "Group"
    }
    for name, item in items.items():
        if not _ITEM_NAME.fullmatch(str(name)):
            errors.append(f'invalid Item name "{name}"')
        if not isinstance(item, Mapping) or not item.get("type"):
            errors.append(f'Item "{name}" has no type')
            continue
        for group in item.get("groups", []):
            if group not in group_names:
                errors.append(f'Item "{name}" references missing Group "{group}"')

        links: list[str] = []
        if channel := item.get("channel"):
            links.append(str(channel))
        links.extend(str(channel) for channel in item.get("channels", {}))
        for channel_uid in links:
            thing_uid, separator, channel_id = channel_uid.rpartition(":")
            thing = things.get(thing_uid)
            if not separator or not isinstance(thing, Mapping):
                errors.append(f'Item "{name}" references missing Thing channel "{channel_uid}"')
            elif channel_id not in thing.get("channels", {}):
                errors.append(f'Item "{name}" references missing channel "{channel_uid}"')

    for thing_uid, thing in things.items():
        if isinstance(thing, Mapping) and (bridge_uid := thing.get("bridge")):
            if bridge_uid not in things:
                errors.append(f'Thing "{thing_uid}" references missing Bridge "{bridge_uid}"')

    for sitemap_name, sitemap in sitemaps.items():
        if not _SITEMAP_NAME.fullmatch(str(sitemap_name)):
            errors.append(f'invalid Sitemap name "{sitemap_name}"')
        if not isinstance(sitemap, Mapping):
            errors.append(f'Sitemap "{sitemap_name}" must be a map')
            continue
        for widget in _iter_sitemap_widgets(sitemap.get("widgets", [])):
            if item_name := widget.get("item"):
                if item_name not in items:
                    errors.append(f'Sitemap "{sitemap_name}" references missing Item "{item_name}"')

    if errors:
        raise YamlModelValidationError(
            "Invalid generated openHAB YAML model:\n- " + "\n- ".join(errors)
        )


def _scalar(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    return json.dumps(str(value), ensure_ascii=False)


def _key(value: Any) -> str:
    text = str(value)
    return text if _PLAIN_KEY.fullmatch(text) else json.dumps(text, ensure_ascii=False)


def _emit(value: Any, indent: int = 0) -> list[str]:
    prefix = " " * indent
    if isinstance(value, Mapping):
        if not value:
            return [prefix + "{}"]
        lines: list[str] = []
        for key, child in value.items():
            key_text = _key(key)
            if isinstance(child, Mapping):
                if child:
                    lines.append(f"{prefix}{key_text}:")
                    lines.extend(_emit(child, indent + 2))
                else:
                    lines.append(f"{prefix}{key_text}: {{}}")
            elif isinstance(child, list):
                if child:
                    lines.append(f"{prefix}{key_text}:")
                    lines.extend(_emit(child, indent + 2))
                else:
                    lines.append(f"{prefix}{key_text}: []")
            else:
                lines.append(f"{prefix}{key_text}: {_scalar(child)}")
        return lines
    if isinstance(value, list):
        if not value:
            return [prefix + "[]"]
        lines = []
        for child in value:
            if isinstance(child, (Mapping, list)):
                lines.append(prefix + "-")
                lines.extend(_emit(child, indent + 2))
            else:
                lines.append(f"{prefix}- {_scalar(child)}")
        return lines
    return [prefix + _scalar(value)]


def render_yaml(model: Mapping[str, Any]) -> str:
    """Render deterministic, dependency-free YAML accepted by openHAB 5.2."""
    validate_model(model)
    return "\n".join(_emit(model)) + "\n"


def write_yaml(path: str | Path, model: Mapping[str, Any]) -> None:
    """Validate and atomically replace a generated YAML file."""
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.tmp")
    temporary.write_text(render_yaml(model), encoding="utf-8")
    temporary.replace(output)
