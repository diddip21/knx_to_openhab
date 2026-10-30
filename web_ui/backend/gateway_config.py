"""Safe readers and pure connection-setting transformations for KNX Things."""

import ipaddress
import json
import re
from collections.abc import Mapping
from typing import Any

import yaml

from knx_things import get_active_things_output

from .deploy_policy import configured_managed_paths, read_managed_file
from .things_format import FORMAT_OUTPUT_KEYS

BRIDGE_UID = "knx:ip:bridge"
_BRIDGE_DECLARATION = re.compile(rf"(?im)^[ \t]*Bridge\s+{re.escape(BRIDGE_UID)}(?=\s|\[)")
_DSL_PROPERTY = re.compile(
    r"(?<![\w.-])(?P<key>[A-Za-z_][\w-]*)\s*=\s*"
    r'(?P<value>"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|[^,\]\s]+)',
    re.DOTALL,
)


class _UniqueKeyLoader(yaml.SafeLoader):
    """Safe YAML loader that rejects ambiguous duplicate mapping keys."""


def _construct_unique_mapping(loader, node, deep=False):
    mapping = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                f"duplicate key {key!r}",
                key_node.start_mark,
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_unique_mapping
)


def _load_yaml(content: str) -> dict[str, Any]:
    try:
        document = yaml.load(content, Loader=_UniqueKeyLoader)
    except yaml.YAMLError as error:
        raise ValueError(f"Invalid YAML KNX Things file: {error}") from error
    if not isinstance(document, dict):
        raise ValueError("Invalid YAML KNX Things file: expected a mapping")
    return document


def _yaml_bridge(document: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    things = document.get("things")
    if not isinstance(things, dict):
        raise ValueError("KNX bridge not found in YAML Things file")
    bridge = things.get(BRIDGE_UID)
    if bridge is None:
        raise ValueError("KNX bridge not found in YAML Things file")
    if not isinstance(bridge, dict):
        raise ValueError("Invalid YAML KNX bridge definition")
    bridge_config = bridge.get("config")
    if not isinstance(bridge_config, dict):
        raise ValueError("Invalid YAML KNX bridge configuration")
    return bridge, bridge_config


def _dsl_bridge_config(content: str) -> tuple[int, int, str]:
    declarations = list(_BRIDGE_DECLARATION.finditer(content))
    if not declarations:
        raise ValueError("KNX bridge not found in DSL Things file")
    if len(declarations) != 1:
        raise ValueError("Multiple KNX bridge definitions found in DSL Things file")

    declaration = declarations[0]
    opening = content.find("[", declaration.end())
    thing_body = content.find("{", declaration.end())
    if opening < 0 or (thing_body >= 0 and thing_body < opening):
        raise ValueError("Invalid DSL KNX bridge configuration")

    quote = None
    escaped = False
    closing = -1
    for index in range(opening + 1, len(content)):
        character = content[index]
        if quote:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == quote:
                quote = None
        elif character in ('"', "'"):
            quote = character
        elif character == "]":
            closing = index
            break
    if closing < 0 or quote:
        raise ValueError("Invalid DSL KNX bridge configuration")
    return opening, closing, content[opening + 1 : closing]


def _dsl_properties(configuration: str) -> list[re.Match[str]]:
    return list(_DSL_PROPERTY.finditer(configuration))


def _get_dsl_property(configuration: str, key: str) -> str | None:
    matches = [match for match in _dsl_properties(configuration) if match.group("key") == key]
    if len(matches) > 1:
        raise ValueError(f"Multiple {key} settings found in KNX bridge configuration")
    return matches[0].group("value") if matches else None


def _split_dsl_segments(configuration: str) -> list[tuple[int, int]]:
    segments = []
    start = 0
    quote = None
    escaped = False
    for index, character in enumerate(configuration):
        if quote:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == quote:
                quote = None
        elif character in ('"', "'"):
            quote = character
        elif character == ",":
            segments.append((start, index))
            start = index + 1
    segments.append((start, len(configuration)))
    return segments


def _set_dsl_property(configuration: str, key: str, value: str) -> str:
    matches = [match for match in _dsl_properties(configuration) if match.group("key") == key]
    if len(matches) > 1:
        raise ValueError(f"Multiple {key} settings found in KNX bridge configuration")
    if matches:
        match = matches[0]
        start, end = match.span("value")
        return configuration[:start] + value + configuration[end:]

    trimmed = configuration.rstrip()
    trailing_whitespace = configuration[len(trimmed) :]
    if not trimmed.strip():
        return configuration + f"{key}={value}"
    separator = "" if trimmed.endswith(",") else ","
    if "\n" in configuration:
        newline = "\r\n" if "\r\n" in configuration else "\n"
        last_line = trimmed.rsplit("\n", 1)[-1]
        indent = re.match(r"[ \t]*", last_line).group(0)
        return f"{trimmed}{separator}{newline}{indent}{key}={value}{trailing_whitespace}"
    return f"{trimmed}{separator} {key}={value}{trailing_whitespace}"


def _remove_dsl_property(configuration: str, key: str) -> str:
    matches = [match for match in _dsl_properties(configuration) if match.group("key") == key]
    if len(matches) > 1:
        raise ValueError(f"Multiple {key} settings found in KNX bridge configuration")
    if not matches:
        return configuration
    match = matches[0]
    segments = _split_dsl_segments(configuration)
    segment_index = next(
        index for index, (start, end) in enumerate(segments) if start <= match.start() < end
    )
    start, end = segments[segment_index]
    if len(segments) == 1:
        return configuration[:start] + configuration[end:]
    if segment_index < len(segments) - 1:
        end = segments[segment_index + 1][0]
    else:
        start = max(0, start - 1)
    return configuration[:start] + configuration[end:]


def _quoted(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _canonical_ip(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("IP address is required")
    try:
        return str(ipaddress.ip_address(value.strip()))
    except ValueError as error:
        raise ValueError(f"Invalid IP address: {value}") from error


def _edit_dsl(content: str, ip_address: str | None) -> str:
    opening, closing, configuration = _dsl_bridge_config(content)
    if ip_address is not None:
        configuration = _set_dsl_property(configuration, "type", _quoted("TUNNEL"))
        configuration = _set_dsl_property(configuration, "ipAddress", _quoted(ip_address))
        if _get_dsl_property(configuration, "portNumber") is None:
            configuration = _set_dsl_property(configuration, "portNumber", "3671")
    else:
        configuration = _set_dsl_property(configuration, "type", _quoted("ROUTER"))
        configuration = _remove_dsl_property(configuration, "ipAddress")
        configuration = _remove_dsl_property(configuration, "portNumber")
        configuration = _set_dsl_property(configuration, "autoReconnectPeriod", "60")
    return content[: opening + 1] + configuration + content[closing:]


def _edit_yaml(content: str, ip_address: str | None) -> str:
    document = _load_yaml(content)
    _bridge, configuration = _yaml_bridge(document)
    if ip_address is not None:
        configuration["type"] = "TUNNEL"
        configuration["ipAddress"] = ip_address
        configuration.setdefault("portNumber", 3671)
    else:
        configuration["type"] = "ROUTER"
        configuration.pop("ipAddress", None)
        configuration.pop("portNumber", None)
        configuration["autoReconnectPeriod"] = 60
    return yaml.safe_dump(document, sort_keys=False, allow_unicode=True)


def update_gateway_file(content: str, format_name: str, ip_address: str) -> str:
    """Set the unique KNX bridge to tunnel mode at a validated IP address."""
    normalized_ip = _canonical_ip(ip_address)
    if format_name == "dsl":
        return _edit_dsl(content, normalized_ip)
    if format_name == "yaml":
        return _edit_yaml(content, normalized_ip)
    raise ValueError(f"Unsupported KNX Things format: {format_name}")


def restore_ets_gateway_file(content: str, format_name: str, detected_ip: str | None) -> str:
    """Restore tunnel mode at the ETS-detected IP, or KNX router mode if absent."""
    normalized_ip = _canonical_ip(detected_ip) if detected_ip is not None else None
    if format_name == "dsl":
        return _edit_dsl(content, normalized_ip)
    if format_name == "yaml":
        return _edit_yaml(content, normalized_ip)
    raise ValueError(f"Unsupported KNX Things format: {format_name}")


def _dsl_unquote(value: str | None) -> str | None:
    if value is None:
        return None
    if value.startswith('"') and value.endswith('"'):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value[1:-1]
    if value.startswith("'") and value.endswith("'"):
        return value[1:-1]
    return value


def _read_gateway_config(content: str, format_name: str) -> tuple[str | None, str | None]:
    if format_name == "dsl":
        _opening, _closing, configuration = _dsl_bridge_config(content)
        mode = _dsl_unquote(_get_dsl_property(configuration, "type"))
        gateway_ip = _dsl_unquote(_get_dsl_property(configuration, "ipAddress"))
        return gateway_ip, mode
    document = _load_yaml(content)
    _bridge, configuration = _yaml_bridge(document)
    gateway_ip = configuration.get("ipAddress")
    mode = configuration.get("type")
    return (str(gateway_ip) if gateway_ip is not None else None, str(mode) if mode else None)


def read_gateway_state(config: Mapping[str, Any], project_root: str) -> dict[str, Any]:
    """Read the active managed bridge configuration without querying OpenHAB."""
    active_path, format_name = get_active_things_output(config)
    key = FORMAT_OUTPUT_KEYS[format_name]
    openhab_root, managed_paths = configured_managed_paths(config, project_root)
    relative_path = managed_paths.get(key)
    if not relative_path:
        raise ValueError(f"No managed Things file is configured for {format_name}")
    try:
        content = read_managed_file(openhab_root, relative_path, managed_paths).decode("utf-8")
    except (OSError, UnicodeError) as error:
        raise ValueError(f"Could not read the managed KNX Things file: {error}") from error
    gateway_ip, gateway_mode = _read_gateway_config(content, format_name)
    saved_override = config.get("devices", {}).get("gateway", {}).get("ip_address", "") or ""
    return {
        "things_format": format_name,
        "managed_path": relative_path,
        "configured_path": active_path,
        "gateway_ip": gateway_ip,
        "gateway_mode": gateway_mode,
        "saved_override": saved_override,
        "reset_available": bool(config.get("_gateway_reset_available", False)),
    }
