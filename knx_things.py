"""Shared structured representation of generated KNX Things and channels."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import yaml

ChannelValue = str | int | float | bool


@dataclass(frozen=True)
class KnxChannel:
    """One generic KNX device channel in a Things model."""

    channel_id: str
    channel_type: str
    label: str
    config: dict[str, ChannelValue]


@dataclass(frozen=True)
class KnxThingsModel:
    """Gateway settings and the channels nested under its generic device."""

    gateway_config: dict[str, ChannelValue]
    channels: tuple[KnxChannel, ...]


def _dsl_value(value: ChannelValue) -> str:
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, str):
        return f'"{value}"'
    if isinstance(value, (int, float)):
        return str(value)
    raise TypeError(f"Unsupported KNX channel config value: {type(value).__name__}")


def render_dsl_channels(model: KnxThingsModel) -> str:
    """Render channel declarations using the generator's existing DSL layout."""
    lines = []
    for channel in model.channels:
        configuration = ", ".join(
            f"{key}={_dsl_value(value)}" for key, value in channel.config.items()
        )
        lines.append(
            f'Type {channel.channel_type}    :   {channel.channel_id}   "{channel.label}"'
            f"   [ {configuration} ]\n"
        )
    return "".join(lines)


def render_yaml(model: KnxThingsModel) -> str:
    """Render a complete OpenHAB YAML Things file from the shared KNX model."""
    things: dict[str, Any] = {
        "knx:ip:bridge": {
            "isBridge": True,
            "config": dict(model.gateway_config),
        }
    }
    if model.channels:
        channels = {
            channel.channel_id: {
                "type": channel.channel_type,
                "label": channel.label,
                "config": dict(channel.config),
            }
            for channel in model.channels
        }
        things["knx:device:bridge:generic"] = {
            "bridge": "knx:ip:bridge",
            "label": "KNX generic device",
            "channels": channels,
        }
    return yaml.safe_dump({"version": 1, "things": things}, sort_keys=False, allow_unicode=True)


def render_inactive_yaml() -> str:
    """Render a valid YAML Things file with no active Things."""
    return yaml.safe_dump({"version": 1}, sort_keys=False)


def render_inactive_dsl() -> str:
    """Render a comment-only placeholder for an inactive DSL Things file."""
    return "// KNX Things inactive (YAML format selected).\n"


def get_active_things_output(configuration: Mapping[str, Any]) -> tuple[str, str]:
    """Return the configured output path and renderer name (DSL by default)."""
    things_format = configuration.get("things_format", "dsl")
    if things_format == "dsl":
        path = configuration.get("things_path")
        if not path:
            raise ValueError("things_path must be configured for DSL Things output")
        return path, "dsl"
    if things_format == "yaml":
        path = configuration.get("yaml_path")
        if not path:
            raise ValueError("yaml_path must be configured for YAML Things output")
        return path, "yaml"
    raise ValueError(f"Unsupported KNX Things format: {things_format}")
