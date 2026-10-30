"""Selection and migration helpers for generator-owned KNX Things files."""

import re
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

from knx_things import render_inactive_dsl, render_inactive_yaml

FORMAT_OUTPUT_KEYS = {"dsl": "things_path", "yaml": "yaml_path"}
THINGS_OUTPUT_KEYS = frozenset(FORMAT_OUTPUT_KEYS.values())
_DSL_BRIDGE = re.compile(r"^Bridge\s+knx:ip:bridge(?:\s|\[)", re.IGNORECASE)


def inactive_content(format_name: str) -> str:
    """Return a valid file that contains no active Things for one format."""
    if format_name == "dsl":
        return render_inactive_dsl()
    if format_name == "yaml":
        return render_inactive_yaml()
    raise ValueError(f"Unsupported KNX Things format: {format_name}")


def plan_things_outputs(
    configuration: Mapping[str, Any],
    managed_paths: Mapping[str, str],
    previous_format: str,
) -> tuple[list[str], str | None]:
    """Select output keys and identify the old-format file to deactivate."""
    current_format = configuration.get("things_format", "dsl")
    if current_format not in FORMAT_OUTPUT_KEYS:
        raise ValueError(f"Unsupported KNX Things format: {current_format}")
    if previous_format not in FORMAT_OUTPUT_KEYS:
        raise ValueError(f"Unsupported previous KNX Things format: {previous_format}")

    active_key = FORMAT_OUTPUT_KEYS[current_format]
    if active_key not in managed_paths:
        raise ValueError(f"{active_key} must be configured for {current_format} Things output")

    output_keys = [key for key in managed_paths if key not in THINGS_OUTPUT_KEYS]
    output_keys.append(active_key)

    if current_format == previous_format:
        return output_keys, None

    inactive_key = FORMAT_OUTPUT_KEYS[previous_format]
    if inactive_key not in managed_paths:
        raise ValueError(f"{inactive_key} must be configured to migrate from {previous_format}")
    return output_keys, inactive_key


def find_unmanaged_bridge_definitions(openhab_root: str, managed_relpaths: set[str]) -> list[str]:
    """Find unowned DSL/YAML files that define the KNX IP bridge UID.

    YAML files are parsed safely. Invalid YAML outside the managed outputs is
    rejected with its path so a migration never proceeds on incomplete data.
    """
    root = Path(openhab_root)
    if not root.is_dir():
        return []

    managed = {PurePosixPath(str(path).replace("\\", "/")).as_posix() for path in managed_relpaths}
    definitions = []
    for path in sorted(root.rglob("*")):
        suffix = path.suffix.lower()
        if suffix not in {".things", ".yaml", ".yml"}:
            continue
        relative = path.relative_to(root).as_posix()
        if relative in managed:
            continue
        if path.is_symlink():
            raise ValueError(f"Cannot safely inspect symlinked configuration file: {path}")
        if not path.is_file():
            continue

        if suffix == ".things":
            try:
                lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError as error:
                raise ValueError(f"Cannot inspect configuration file {path}: {error}") from error
            if any(
                _DSL_BRIDGE.match(line.strip())
                for line in lines
                if not line.strip().startswith("//")
            ):
                definitions.append(relative)
            continue

        try:
            document = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, yaml.YAMLError) as error:
            raise ValueError(f"Cannot inspect YAML configuration file {path}: {error}") from error
        things = document.get("things") if isinstance(document, dict) else None
        if isinstance(things, dict) and "knx:ip:bridge" in things:
            definitions.append(relative)

    return definitions


def assert_no_unmanaged_bridge_definitions(openhab_root: str, managed_relpaths: set[str]) -> None:
    """Abort a migration when any unmanaged configuration owns the KNX bridge UID."""
    definitions = find_unmanaged_bridge_definitions(openhab_root, managed_relpaths)
    if definitions:
        raise ValueError("Unmanaged KNX bridge definition found: " + ", ".join(definitions))


def validate_yaml_compatibility(installed_version: str | None) -> str | None:
    """Reject known OpenHAB versions before 5.0 and disclose an unknown version."""
    if not installed_version:
        return "OpenHAB version is unknown; YAML Things compatibility is not confirmed."
    match = re.match(r"^\s*(\d+)\.(\d+)", installed_version)
    if not match:
        return "OpenHAB version is unknown; YAML Things compatibility is not confirmed."
    major, minor = (int(value) for value in match.groups())
    if major < 5:
        raise ValueError("YAML Things require OpenHAB 5.0 or newer")
    return None
