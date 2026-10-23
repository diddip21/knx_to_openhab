#!/usr/bin/env python3
"""Remove only inactive generated outputs from the root-owned setup manifest.

This helper is installed root-owned outside the application directory and uses
only the Python standard library. It must never import code from the writable
application tree while running with elevated privileges.
"""

from __future__ import annotations

import json
import os
import shlex
import stat
import sys
from pathlib import Path, PurePosixPath

PATHS_FILE = Path("/etc/knx_to_openhab/paths.env")
MANIFEST_NAME = "managed_outputs.json"
OUTPUT_SPECS = {
    "items_path": ("items", ".items"),
    "things_path": ("things", ".things"),
    "sitemaps_path": ("sitemaps", ".sitemap"),
    "influx_path": ("persistence", ".persist"),
    "fenster_path": ("rules", ".rules"),
    "yaml_path": ("yaml", ".yaml"),
}
REPORT_NAMES = {
    "unknown_report.json",
    "partial_report.json",
    "completeness_report.json",
}
DIRECTORY_FLAGS = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)


def _read_root_owned_json(path: Path) -> dict:
    try:
        info = path.lstat()
    except OSError as error:
        raise ValueError(f"Required root-owned file is unavailable: {path}") from error
    if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
        raise ValueError(f"Refusing an unsafe root-owned file: {path}")
    with path.open(encoding="utf-8") as source:
        value = json.load(source)
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object in {path}")
    return value


def _load_paths_file() -> dict[str, str]:
    try:
        info = PATHS_FILE.lstat()
    except OSError as error:
        raise ValueError(f"Installation paths are not configured: {PATHS_FILE}") from error
    if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
        raise ValueError(f"Refusing an unsafe installation paths file: {PATHS_FILE}")
    values = {}
    for line in PATHS_FILE.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        name, raw_value = stripped.split("=", 1)
        if name not in {"KNXOH_CONFIG_DIR"}:
            continue
        parsed = shlex.split(raw_value, posix=True)
        if len(parsed) == 1:
            values[name] = parsed[0]
    return values


def _validate_manifest(manifest):
    root_value = manifest.get("openhab_root")
    managed = manifest.get("managed_files")
    if not isinstance(root_value, str) or not os.path.isabs(root_value):
        raise ValueError("The managed-output manifest has an invalid OpenHAB root")
    root = os.path.abspath(root_value)
    if os.path.realpath(root) != root:
        raise ValueError("The managed-output root must not contain symlink components")
    try:
        root_info = os.lstat(root)
    except OSError as error:
        raise ValueError("The managed-output root is unavailable") from error
    if not stat.S_ISDIR(root_info.st_mode):
        raise ValueError("The managed-output root must be a real directory")
    if not isinstance(managed, dict):
        raise ValueError("The managed-output manifest has no file map")
    allowed_keys = set(OUTPUT_SPECS) | REPORT_NAMES
    if not set(managed).issubset(allowed_keys):
        raise ValueError("The managed-output manifest contains an unsupported file key")

    for key, relative in managed.items():
        if not isinstance(relative, str) or not relative or "\\" in relative:
            raise ValueError(f"The managed-output path for {key} is invalid")
        parts = PurePosixPath(relative).parts
        if not parts or any(part in ("", ".", "..") for part in parts):
            raise ValueError(f"The managed-output path for {key} is unsafe")
        if key in OUTPUT_SPECS:
            directory, suffix = OUTPUT_SPECS[key]
            if len(parts) != 2 or parts[0] != directory or not parts[1].endswith(suffix):
                raise ValueError(f"The managed-output path for {key} is outside its output class")
        elif relative != key:
            raise ValueError(f"The managed report path for {key} is invalid")
    if len(set(managed.values())) != len(managed):
        raise ValueError("The managed-output manifest contains duplicate paths")
    return root, managed


def _open_directory(root: str, relative: str) -> int:
    current_fd = os.open(root, DIRECTORY_FLAGS | NOFOLLOW)
    try:
        for part in PurePosixPath(relative).parts if relative else ():
            if part in ("", ".", ".."):
                raise ValueError("Managed-output directory contains an unsafe component")
            next_fd = os.open(part, DIRECTORY_FLAGS | NOFOLLOW, dir_fd=current_fd)
            os.close(current_fd)
            current_fd = next_fd
        return current_fd
    except Exception:
        os.close(current_fd)
        raise


def _read_all(fd: int) -> bytes:
    chunks = []
    while True:
        chunk = os.read(fd, 1024 * 1024)
        if not chunk:
            return b"".join(chunks)
        chunks.append(chunk)


def _write_all(fd: int, content: bytes) -> None:
    remaining = memoryview(content)
    while remaining:
        written = os.write(fd, remaining)
        if written <= 0:
            raise OSError("Short write while restoring managed output")
        remaining = remaining[written:]
    os.fsync(fd)


def _retire(root: str, relatives: set[str], managed: dict[str, str]) -> int:
    allowed = set(managed.values())
    if not relatives.issubset(allowed):
        raise ValueError("Cannot retire a file that is not in the managed-output manifest")

    prepared = []
    for relative in sorted(relatives):
        parts = PurePosixPath(relative).parts
        parent_fd = _open_directory(root, "/".join(parts[:-1]))
        try:
            try:
                info = os.stat(parts[-1], dir_fd=parent_fd, follow_symlinks=False)
            except FileNotFoundError:
                os.close(parent_fd)
                continue
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise ValueError(f"Retired output is not a single-link regular file: {relative}")
            fd = os.open(parts[-1], os.O_RDONLY | NOFOLLOW, dir_fd=parent_fd)
            try:
                opened_info = os.fstat(fd)
                if (
                    not stat.S_ISREG(opened_info.st_mode)
                    or opened_info.st_nlink != 1
                    or (opened_info.st_dev, opened_info.st_ino) != (info.st_dev, info.st_ino)
                ):
                    raise ValueError(f"Retired output changed during validation: {relative}")
                content = _read_all(fd)
            finally:
                os.close(fd)
            prepared.append(
                (parent_fd, parts[-1], relative, info.st_mode, info.st_uid, info.st_gid, content)
            )
        except Exception:
            os.close(parent_fd)
            for entry in prepared:
                os.close(entry[0])
            raise

    removed = []
    try:
        for entry in prepared:
            os.unlink(entry[1], dir_fd=entry[0])
            removed.append(entry)
    except Exception as removal_error:
        recovery_errors = []
        for entry in reversed(removed):
            parent_fd, filename, relative, mode, uid, gid, content = entry
            try:
                fd = os.open(
                    filename,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | NOFOLLOW,
                    stat.S_IMODE(mode),
                    dir_fd=parent_fd,
                )
                try:
                    os.fchown(fd, uid, gid)
                    os.fchmod(fd, stat.S_IMODE(mode))
                    _write_all(fd, content)
                finally:
                    os.close(fd)
            except Exception as recovery_error:
                recovery_errors.append(f"{relative}: {recovery_error}")
        if recovery_errors:
            raise ValueError(
                "Retirement failed and files could not be fully restored: "
                + "; ".join(recovery_errors)
            ) from removal_error
        raise
    finally:
        for entry in prepared:
            os.close(entry[0])
    return len(removed)


def main(argv=None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1 or args[0] not in {"legacy", "yaml"}:
        print("usage: knxohui-retire-managed-outputs legacy|yaml", file=sys.stderr)
        return 2

    output_format = args[0]
    obsolete_keys = (
        {"items_path", "things_path", "sitemaps_path"}
        if output_format == "yaml"
        else {"yaml_path"}
    )
    try:
        saved_paths = _load_paths_file()
        config_dir = Path(saved_paths.get("KNXOH_CONFIG_DIR", "/etc/knx_to_openhab"))
        if not config_dir.is_absolute():
            raise ValueError("Configuration directory must be absolute")
        manifest = _read_root_owned_json(config_dir / MANIFEST_NAME)
        root, managed = _validate_manifest(manifest)
        obsolete_paths = {managed[key] for key in obsolete_keys if key in managed}
        print(_retire(root, obsolete_paths, managed))
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"Cannot retire inactive generated outputs: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
