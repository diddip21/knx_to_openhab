"""Selection and migration helpers for generator-owned KNX Things files."""

import re
from pathlib import Path, PurePosixPath

import yaml

FORMAT_OUTPUT_KEYS = {"dsl": "things_path", "yaml": "yaml_path"}
_DSL_BRIDGE = re.compile(r"^Bridge\s+knx:ip:bridge(?:\s|\[)", re.IGNORECASE)


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
    """Reject known OpenHAB versions before 5.2 and disclose an unknown version."""
    if not installed_version:
        return "OpenHAB version is unknown; YAML Things compatibility is not confirmed."
    match = re.match(r"^\s*(\d+)\.(\d+)", installed_version)
    if not match:
        return "OpenHAB version is unknown; YAML Things compatibility is not confirmed."
    major, minor = (int(value) for value in match.groups())
    if (major, minor) < (5, 2):
        raise ValueError("OpenHAB YAML configuration requires OpenHAB 5.2 or newer")
    return None
