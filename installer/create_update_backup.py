"""Create and verify a private snapshot before an in-place application update."""

from __future__ import annotations

import os
import sys
import tarfile
import tempfile
import time
from pathlib import Path, PurePosixPath
from typing import Iterable

from knxoh_paths import get_paths

_EXCLUDED_PARTS = {".git", "venv", ".venv", "__pycache__"}
_CHUNK_SIZE = 1024 * 1024


def _resolve_directory(label: str, raw_path: Path) -> Path:
    if raw_path.is_symlink():
        raise ValueError(f"Refusing a symlinked {label} directory: {raw_path}")
    resolved = raw_path.resolve(strict=True)
    if not resolved.is_dir():
        raise ValueError(f"The {label} path is not a directory: {resolved}")
    return resolved


def _archive_filter(member: tarfile.TarInfo) -> tarfile.TarInfo | None:
    path = PurePosixPath(member.name)
    if any(part in _EXCLUDED_PARTS for part in path.parts):
        return None
    if any(part.endswith(".pyc") for part in path.parts):
        return None
    return member


def _verify_archive(archive_path: Path, expected_roots: Iterable[str]) -> None:
    with tarfile.open(archive_path, mode="r:gz") as archive:
        members = archive.getmembers()
        names = {member.name for member in members}
        for root in expected_roots:
            if root not in names and not any(name.startswith(f"{root}/") for name in names):
                raise tarfile.ReadError(f"Backup is missing the {root} snapshot")

        for member in members:
            path = PurePosixPath(member.name)
            if path.is_absolute() or ".." in path.parts:
                raise tarfile.ReadError(f"Backup contains an unsafe path: {member.name}")
            if not member.isfile():
                continue
            stream = archive.extractfile(member)
            if stream is None:
                raise tarfile.ReadError(f"Could not read backup member: {member.name}")
            with stream:
                while stream.read(_CHUNK_SIZE):
                    pass


def create_update_backup(
    install_dir: Path,
    config_dir: Path,
    data_dir: Path,
    generator_config_file: Path,
    backup_dir: Path,
) -> Path:
    """Snapshot application files, external configuration, and runtime data."""
    install_root = _resolve_directory("application", Path(install_dir))
    config_root = _resolve_directory("configuration", Path(config_dir))
    data_root = _resolve_directory("runtime data", Path(data_dir))

    roots: list[tuple[str, Path]] = [("application", install_root)]
    for label, root in (("configuration", config_root), ("runtime data", data_root)):
        if root == install_root or install_root in root.parents:
            continue
        if root in install_root.parents:
            raise ValueError(f"The {label} directory contains the application directory")
        roots.append((label, root))

    for index, (label, root) in enumerate(roots):
        for other_label, other_root in roots[index + 1 :]:
            if root in other_root.parents or other_root in root.parents:
                raise ValueError(f"The {label} and {other_label} directories overlap")

    generator_file = Path(generator_config_file)
    if generator_file.is_symlink():
        raise ValueError(f"Refusing a symlinked generator configuration: {generator_file}")
    if generator_file.exists():
        generator_file = generator_file.resolve(strict=True)
        if not generator_file.is_file():
            raise ValueError(f"Generator configuration is not a regular file: {generator_file}")
        if not any(root == generator_file or root in generator_file.parents for _, root in roots):
            roots.append(("generator-config", generator_file))

    backup_root = Path(backup_dir).expanduser()
    if not backup_root.is_absolute():
        raise ValueError(f"Backup directory must be absolute: {backup_root}")
    if backup_root.is_symlink():
        raise ValueError(f"Refusing a symlinked backup directory: {backup_root}")
    backup_root = backup_root.resolve(strict=False)
    for label, root in roots:
        if backup_root == root or root in backup_root.parents:
            raise ValueError(f"Backup directory must be outside the {label} directory")
    backup_root.mkdir(parents=True, exist_ok=True, mode=0o750)
    backup_root = backup_root.resolve(strict=True)
    if not backup_root.is_dir():
        raise ValueError(f"Backup path is not a directory: {backup_root}")

    timestamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    descriptor, temp_name = tempfile.mkstemp(
        prefix=f".pre-update-{timestamp}-",
        suffix=".tmp",
        dir=backup_root,
    )
    os.close(descriptor)
    temp_path = Path(temp_name)
    final_path = temp_path.with_suffix(".tar.gz")

    try:
        with tarfile.open(temp_path, mode="w:gz") as archive:
            for label, root in roots:
                arcname = label if root.is_dir() else f"{label}/{root.name}"
                archive.add(root, arcname=arcname, recursive=True, filter=_archive_filter)

        _verify_archive(temp_path, (label for label, _ in roots))
        with temp_path.open("rb") as archive_file:
            os.fsync(archive_file.fileno())
        os.replace(temp_path, final_path)
        os.chmod(final_path, 0o600)
        directory_fd = os.open(backup_root, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        return final_path
    except Exception:
        temp_path.unlink(missing_ok=True)
        final_path.unlink(missing_ok=True)
        raise


def main() -> int:
    paths = get_paths()
    try:
        backup_path = create_update_backup(
            paths.install_dir,
            paths.config_dir,
            paths.data_dir,
            paths.generator_config_file,
            paths.backup_dir,
        )
    except (OSError, tarfile.TarError, ValueError) as error:
        print(error, file=sys.stderr)
        return 1
    print(backup_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
