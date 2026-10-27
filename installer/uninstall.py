"""Safely resolve the configured paths used by the uninstaller."""

from __future__ import annotations

import os
import posixpath
import shlex
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Mapping

PATH_DEFAULTS = {
    "KNXOH_INSTALL_DIR": "/opt/knx_to_openhab",
    "KNXOH_CONFIG_DIR": "/etc/knx_to_openhab",
    "KNXOH_DATA_DIR": "/var/lib/knx_to_openhab",
    "KNXOH_BACKUP_DIR": "/var/backups/knx_to_openhab",
}
PATHS_FILE = Path("/etc/knx_to_openhab/paths.env")
PROTECTED_DIRECTORIES = {
    PurePosixPath("/"),
    PurePosixPath("/etc"),
    PurePosixPath("/usr"),
    PurePosixPath("/var"),
    PurePosixPath("/opt"),
    PurePosixPath("/home"),
    PurePosixPath("/root"),
    PurePosixPath("/tmp"),
    PurePosixPath("/run"),
}


class UninstallError(ValueError):
    """Raised when an install path is unsafe or malformed."""


@dataclass(frozen=True)
class UninstallPaths:
    install_dir: PurePosixPath
    config_dir: PurePosixPath
    data_dir: PurePosixPath
    backup_dir: PurePosixPath


def _read_saved_paths(paths_file: Path) -> dict[str, str]:
    try:
        lines = paths_file.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return {}
    except OSError as error:
        raise UninstallError(f"Cannot read saved path configuration {paths_file}: {error}") from error

    saved: dict[str, str] = {}
    for line_number, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        name, raw_value = stripped.split("=", 1)
        if name not in PATH_DEFAULTS:
            continue
        if name in saved:
            raise UninstallError(f"Duplicate {name} in {paths_file}:{line_number}")
        try:
            values = shlex.split(raw_value, posix=True)
        except ValueError as error:
            raise UninstallError(f"Invalid quoting for {name} in {paths_file}:{line_number}") from error
        if len(values) != 1 or not values[0]:
            raise UninstallError(f"Expected one non-empty path for {name} in {paths_file}:{line_number}")
        saved[name] = values[0]
    return saved


def _parse_path(name: str, value: str) -> PurePosixPath:
    if not value or any(character in value for character in "\r\n\0"):
        raise UninstallError(f"{name} must be a non-empty path without control characters")
    if not value.startswith("/"):
        raise UninstallError(f"{name} must be an absolute path: {value}")
    raw_parts = value.split("/")
    if ".." in raw_parts:
        raise UninstallError(f"{name} must not contain parent traversal: {value}")
    normalized = PurePosixPath(posixpath.normpath(value))
    if normalized == PurePosixPath("/"):
        raise UninstallError(f"Refusing to use the filesystem root as {name}")
    if normalized in PROTECTED_DIRECTORIES:
        raise UninstallError(f"Refusing to use a system directory as {name}: {normalized}")

    if os.name == "posix":
        candidate = Path("/")
        for component in normalized.parts[1:]:
            candidate = candidate / component
            if candidate.is_symlink():
                raise UninstallError(f"Refusing symlinked {name}: {candidate}")
    return normalized


def _overlaps(left: PurePosixPath, right: PurePosixPath) -> bool:
    return left == right or left in right.parents or right in left.parents


def resolve_uninstall_paths(
    env: Mapping[str, str], paths_file: Path = PATHS_FILE
) -> UninstallPaths:
    """Resolve path overrides and saved installer paths without running a shell."""
    saved = _read_saved_paths(Path(paths_file))
    resolved = {
        name: _parse_path(name, env.get(name, saved.get(name, default)))
        for name, default in PATH_DEFAULTS.items()
    }

    install_dir = resolved["KNXOH_INSTALL_DIR"]
    external_dirs = (
        resolved["KNXOH_CONFIG_DIR"],
        resolved["KNXOH_DATA_DIR"],
        resolved["KNXOH_BACKUP_DIR"],
    )
    named_external_dirs = (
        ("configuration", external_dirs[0]),
        ("runtime data", external_dirs[1]),
        ("backups", external_dirs[2]),
    )
    for index, (left_name, left) in enumerate(named_external_dirs):
        if _overlaps(install_dir, left):
            raise UninstallError(
                f"The {left_name} path overlaps the application directory: {left}"
            )
        for right_name, right in named_external_dirs[index + 1 :]:
            if _overlaps(left, right):
                raise UninstallError(
                    f"The {left_name} path overlaps the {right_name} path: {left}, {right}"
                )

    return UninstallPaths(
        install_dir=install_dir,
        config_dir=resolved["KNXOH_CONFIG_DIR"],
        data_dir=resolved["KNXOH_DATA_DIR"],
        backup_dir=resolved["KNXOH_BACKUP_DIR"],
    )
