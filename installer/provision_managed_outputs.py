#!/usr/bin/python3
"""Provision the single configured YAML output without importing application code."""

from __future__ import annotations

import json
import os
import re
import shlex
import stat
import sys
from pathlib import Path

DEFAULT_PATHS_FILE = Path("/etc/knx_to_openhab/paths.env")
SERVICE_USER = "knxohui"
OPENHAB_GROUP = "openhab"
TARGET_MODE = 0o640
_DIRECTORY_FLAGS = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_YAML_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*\.yaml$")


class ProvisionError(ValueError):
    """Raised when the configured YAML target is outside the managed boundary."""


def _path_text(value: str | os.PathLike, label: str) -> str:
    if not isinstance(value, (str, os.PathLike)):
        raise ProvisionError(f"{label} must be a filesystem path")
    text = os.fspath(value)
    if not text or "\0" in text:
        raise ProvisionError(f"{label} must be a non-empty filesystem path")
    return text


def validate_managed_yaml_target(openhab_root, install_root, configured_yaml_path) -> Path:
    """Resolve one configured target and require a direct ``yaml/*.yaml`` child."""
    root_text = _path_text(openhab_root, "OpenHAB root")
    install_text = _path_text(install_root, "Install root")
    raw_text = _path_text(configured_yaml_path, "YAML target")
    root = Path(os.path.abspath(root_text))
    install = Path(os.path.abspath(install_text))
    raw = Path(raw_text).expanduser()

    if ".." in raw.parts:
        raise ProvisionError("YAML target must not contain path traversal")
    if raw.is_absolute():
        candidate = raw
    elif raw.parts and raw.parts[0] == "openhab":
        candidate = root.joinpath(*raw.parts[1:])
    elif raw.parts and raw.parts[0] == "yaml":
        candidate = root.joinpath(*raw.parts)
    elif "yaml" in raw.parts:
        # Match config.py's legacy mapping for paths containing a yaml component.
        candidate = root / "yaml" / raw.name
    else:
        candidate = install / raw

    candidate = Path(os.path.abspath(candidate))
    expected_directory = root / "yaml"
    if candidate.parent != expected_directory or not _YAML_NAME.fullmatch(candidate.name):
        raise ProvisionError("YAML target must be one .yaml file directly under OpenHAB yaml/")
    return candidate


def _secure_directory_mode(mode: int) -> int:
    return (stat.S_IMODE(mode) & ~0o022) | 0o050


def _set_directory_policy(fd: int, group_id: int, created: bool) -> None:
    info = os.fstat(fd)
    if not stat.S_ISDIR(info.st_mode):
        raise ProvisionError("OpenHAB yaml target directory is not a directory")
    if hasattr(os, "fchown") and (not hasattr(os, "geteuid") or os.geteuid() == 0):
        os.fchown(fd, 0, group_id)
    mode = 0o750 if created else _secure_directory_mode(info.st_mode)
    if hasattr(os, "fchmod"):
        os.fchmod(fd, mode)


def _open_yaml_directory(root_fd: int, group_id: int) -> int:
    try:
        fd = os.open("yaml", _DIRECTORY_FLAGS | _NOFOLLOW, dir_fd=root_fd)
        created = False
    except FileNotFoundError:
        os.mkdir("yaml", 0o755, dir_fd=root_fd)
        fd = os.open("yaml", _DIRECTORY_FLAGS | _NOFOLLOW, dir_fd=root_fd)
        created = True
    try:
        _set_directory_policy(fd, group_id, created)
        return fd
    except Exception:
        os.close(fd)
        raise


def _check_regular_file(fd: int, path: Path) -> None:
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise ProvisionError(f"YAML target must be a single-link regular file: {path}")


def _set_target_policy(fd: int, path: Path, user_id: int, group_id: int) -> None:
    _check_regular_file(fd, path)
    if hasattr(os, "fchown"):
        os.fchown(fd, user_id, group_id)
    if hasattr(os, "fchmod"):
        os.fchmod(fd, TARGET_MODE)


def _provision_with_directory_fds(root: Path, target: Path, user_id: int, group_id: int) -> None:
    root_fd = os.open(root, _DIRECTORY_FLAGS | _NOFOLLOW)
    try:
        yaml_fd = _open_yaml_directory(root_fd, group_id)
        try:
            try:
                target_fd = os.open(
                    target.name,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | _NOFOLLOW,
                    TARGET_MODE,
                    dir_fd=yaml_fd,
                )
            except FileExistsError:
                target_fd = os.open(
                    target.name,
                    os.O_RDONLY | _NOFOLLOW,
                    dir_fd=yaml_fd,
                )
            try:
                _set_target_policy(target_fd, target, user_id, group_id)
            finally:
                os.close(target_fd)
        finally:
            os.close(yaml_fd)
    finally:
        os.close(root_fd)


def _provision_with_paths(root: Path, target: Path, user_id: int, group_id: int) -> None:
    """Portable fallback for development hosts lacking dir_fd support."""
    yaml_directory = root / "yaml"
    try:
        yaml_directory.mkdir(mode=0o755)
        created = True
    except FileExistsError:
        created = False
    directory_info = yaml_directory.lstat()
    if stat.S_ISLNK(directory_info.st_mode) or not stat.S_ISDIR(directory_info.st_mode):
        raise ProvisionError("OpenHAB yaml target directory must not be a symlink")
    if hasattr(os, "chown") and (not hasattr(os, "geteuid") or os.geteuid() == 0):
        os.chown(yaml_directory, 0, group_id, follow_symlinks=False)
    mode = 0o750 if created else _secure_directory_mode(directory_info.st_mode)
    if os.name == "posix":
        os.chmod(yaml_directory, mode, follow_symlinks=False)
    else:
        os.chmod(yaml_directory, mode)

    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | _NOFOLLOW
    try:
        target_fd = os.open(target, flags, TARGET_MODE)
    except FileExistsError:
        info = target.lstat()
        if stat.S_ISLNK(info.st_mode):
            raise ProvisionError(f"YAML target must not be a symlink: {target}")
        target_fd = os.open(target, os.O_RDONLY | _NOFOLLOW)
    try:
        _set_target_policy(target_fd, target, user_id, group_id)
    finally:
        os.close(target_fd)


def provision_managed_yaml(openhab_root, target_path, user_id: int, group_id: int) -> Path:
    """Create the missing managed YAML target; never replace its existing contents."""
    root = Path(os.path.realpath(_path_text(openhab_root, "OpenHAB root")))
    root_info = root.lstat()
    if stat.S_ISLNK(root_info.st_mode) or not stat.S_ISDIR(root_info.st_mode):
        raise ProvisionError(f"OpenHAB root must be a real directory: {root}")
    target = validate_managed_yaml_target(root, root, target_path)

    try:
        if (
            os.open in getattr(os, "supports_dir_fd", set())
            and os.mkdir in getattr(os, "supports_dir_fd", set())
            and _NOFOLLOW
        ):
            _provision_with_directory_fds(root, target, user_id, group_id)
        else:
            _provision_with_paths(root, target, user_id, group_id)
    except ProvisionError:
        raise
    except OSError as error:
        raise ProvisionError(f"Cannot provision managed YAML target {target}: {error}") from error
    return target


def _require_trusted_directory_chain(path: Path, service_uid: int) -> None:
    for directory in (path, *path.parents):
        try:
            info = directory.lstat()
        except OSError as error:
            raise ProvisionError(
                f"Cannot inspect protected directory {directory}: {error}"
            ) from error
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            raise ProvisionError(f"Protected path component must be a real directory: {directory}")
        if info.st_uid == service_uid or stat.S_IMODE(info.st_mode) & 0o022:
            raise ProvisionError(
                f"Protected path component may be writable by the service user: {directory}"
            )


def _read_data_paths(paths_file: Path, service_uid: int) -> dict[str, Path]:
    _require_trusted_directory_chain(paths_file.parent, service_uid)
    try:
        info = paths_file.lstat()
    except OSError as error:
        raise ProvisionError(
            f"Cannot inspect installer paths file {paths_file}: {error}"
        ) from error
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise ProvisionError("Installer paths file must be a regular non-symlink file")
    if info.st_uid != 0 or stat.S_IMODE(info.st_mode) & 0o022:
        raise ProvisionError("Installer paths file must be root-owned and not group/other writable")

    values = {}
    try:
        lines = paths_file.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise ProvisionError(f"Cannot read installer paths file {paths_file}: {error}") from error
    for line in lines:
        name, separator, raw_value = line.partition("=")
        if not separator or name not in {
            "KNXOH_INSTALL_DIR",
            "KNXOH_CONFIG_DIR",
            "KNXOH_DATA_DIR",
        }:
            continue
        try:
            parsed = shlex.split(raw_value, posix=True)
        except ValueError as error:
            raise ProvisionError(f"Invalid value for {name} in installer paths file") from error
        if len(parsed) != 1 or name in values:
            raise ProvisionError(f"Invalid or duplicate value for {name} in installer paths file")
        path = Path(parsed[0]).expanduser()
        if not path.is_absolute():
            raise ProvisionError(f"{name} must be an absolute path")
        values[name] = path

    required = ("KNXOH_INSTALL_DIR", "KNXOH_CONFIG_DIR", "KNXOH_DATA_DIR")
    if any(name not in values for name in required):
        raise ProvisionError("Installer paths file is missing a required installation path")
    return values


def _require_protected_file(path: Path, service_uid: int) -> None:
    _require_trusted_directory_chain(path.parent, service_uid)
    try:
        info = path.lstat()
    except OSError as error:
        raise ProvisionError(f"Cannot inspect protected configuration {path}: {error}") from error
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise ProvisionError(f"Protected configuration must be a regular file: {path}")
    if info.st_uid != 0 or stat.S_IMODE(info.st_mode) & 0o022:
        raise ProvisionError(f"Protected configuration must be root-owned: {path}")
    if info.st_uid == service_uid:
        raise ProvisionError(f"Protected configuration must not be service-owned: {path}")


def _require_protected_directory(path: Path, service_uid: int) -> None:
    _require_trusted_directory_chain(path, service_uid)
    try:
        info = path.lstat()
    except OSError as error:
        raise ProvisionError(f"Cannot inspect protected directory {path}: {error}") from error
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise ProvisionError(f"Protected configuration directory must be a real directory: {path}")
    if info.st_uid != 0 or stat.S_IMODE(info.st_mode) & 0o022:
        raise ProvisionError(f"Protected configuration directory must be root-owned: {path}")
    if info.st_uid == service_uid:
        raise ProvisionError(f"Protected directory must not be service-owned: {path}")


def _configured_target(paths: dict[str, Path], service_uid: int) -> tuple[Path, Path]:
    config_dir = paths["KNXOH_CONFIG_DIR"]
    install_root = paths["KNXOH_INSTALL_DIR"]
    data_dir = paths["KNXOH_DATA_DIR"]
    _require_protected_directory(config_dir, service_uid)
    openhab_root_path = config_dir / "managed_openhab_root"
    _require_protected_file(openhab_root_path, service_uid)
    try:
        root_values = openhab_root_path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise ProvisionError(f"Cannot read protected OpenHAB root: {error}") from error
    if len(root_values) != 1 or not root_values[0]:
        raise ProvisionError("Protected OpenHAB root file must contain one absolute path")
    openhab_root = Path(root_values[0])
    if not openhab_root.is_absolute():
        raise ProvisionError("Protected OpenHAB root must be an absolute path")
    _require_trusted_directory_chain(openhab_root, service_uid)

    generator_path = data_dir / "generator.json"
    try:
        generator_info = generator_path.lstat()
    except FileNotFoundError:
        generator = {}
    except OSError as error:
        raise ProvisionError(f"Cannot inspect generator configuration: {error}") from error
    else:
        if stat.S_ISLNK(generator_info.st_mode) or not stat.S_ISREG(generator_info.st_mode):
            raise ProvisionError("Generator configuration must be a regular non-symlink file")
        try:
            generator = json.loads(generator_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ProvisionError(f"Cannot read generator configuration: {error}") from error
        if not isinstance(generator, dict):
            raise ProvisionError("Generator configuration must be a JSON object")

    configured_yaml = generator.get("yaml_path", "openhab/yaml/knx.yaml")
    target = validate_managed_yaml_target(openhab_root, install_root, configured_yaml)
    return openhab_root, target


def main() -> int:
    if len(sys.argv) != 1:
        print("This helper accepts no arguments.", file=sys.stderr)
        return 2
    if not hasattr(os, "geteuid") or os.geteuid() != 0:
        print("This helper must be run as root.", file=sys.stderr)
        return 1

    try:
        import grp
        import pwd

        service_uid = pwd.getpwnam(SERVICE_USER).pw_uid
        openhab_gid = grp.getgrnam(OPENHAB_GROUP).gr_gid
        paths = _read_data_paths(DEFAULT_PATHS_FILE, service_uid)
        openhab_root, target = _configured_target(paths, service_uid)
        provision_managed_yaml(openhab_root, target, service_uid, openhab_gid)
    except (KeyError, OSError, ProvisionError, ValueError) as error:
        print(f"Cannot provision managed OpenHAB YAML output: {error}", file=sys.stderr)
        return 1

    print(f"Provisioned managed YAML output {target}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
