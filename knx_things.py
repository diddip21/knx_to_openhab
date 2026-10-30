"""Shared structured representation of generated KNX Things and channels."""

from dataclasses import dataclass

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
