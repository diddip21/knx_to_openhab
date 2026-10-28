#!/usr/bin/env python3
"""Versioned, snapshot-backed migrations for external application settings."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable

SCHEMA_VERSION_KEY = "schema_version"


def _migration_1(config: dict) -> dict:
    """Persist settings defaults that were previously supplied only at runtime."""
    config.setdefault("trusted_proxy_hops", 0)
    config.setdefault("session_max_age_seconds", 43200)
    return config


MIGRATIONS: tuple[Callable[[dict], dict], ...] = (_migration_1,)
LATEST_SCHEMA_VERSION = len(MIGRATIONS)


def _atomic_write(path: Path, contents: str, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent, text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as destination:
            destination.write(contents)
            destination.flush()
            os.fsync(destination.fileno())
        os.chmod(temporary_name, mode)
        os.replace(temporary_name, path)
    except Exception:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def _absolute_path(path: str | Path) -> Path:
    candidate = Path(os.path.abspath(Path(path).expanduser()))
    current = Path(candidate.anchor)
    for part in candidate.parts[1:]:
        current = current / part
        if current.is_symlink():
            raise ValueError(f"Refusing to snapshot or restore a symlink path: {current}")
    if candidate.exists() and not candidate.is_file():
        raise ValueError(f"Snapshot target is not a regular file: {candidate}")
    return candidate


def create_snapshot(paths: Iterable[str | Path], backup_dir: str | Path) -> Path:
    """Save only the named files (and missing-file state) for later rollback."""
    unique_paths = sorted({_absolute_path(path) for path in paths}, key=str)
    if not unique_paths:
        raise ValueError("A migration snapshot requires at least one target path")

    snapshot_root = Path(backup_dir).expanduser().resolve() / "config-migrations"
    snapshot_root.mkdir(parents=True, exist_ok=True)
    snapshot_dir = snapshot_root / (
        datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ") + "-" + uuid.uuid4().hex
    )
    snapshot_dir.mkdir(mode=0o700)
    files_dir = snapshot_dir / "files"
    files_dir.mkdir(mode=0o700)
    entries = []

    try:
        for index, path in enumerate(unique_paths):
            entry = {"path": str(path), "existed": path.is_file()}
            if entry["existed"]:
                snapshot_name = f"files/{index:04d}"
                snapshot_file = snapshot_dir / snapshot_name
                contents = path.read_bytes()
                snapshot_file.write_bytes(contents)
                os.chmod(snapshot_file, 0o600)
                entry.update(
                    {
                        "snapshot": snapshot_name,
                        "mode": stat.S_IMODE(path.stat().st_mode),
                        "sha256": hashlib.sha256(contents).hexdigest(),
                    }
                )
            entries.append(entry)

        manifest = {
            "format_version": 1,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "files": entries,
        }
        manifest_path = snapshot_dir / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        os.chmod(manifest_path, 0o600)
    except Exception:
        shutil.rmtree(snapshot_dir, ignore_errors=True)
        raise
    return snapshot_dir


def restore_snapshot(snapshot_dir: str | Path) -> None:
    """Restore original bytes and modes, or remove files absent at snapshot time."""
    snapshot_dir = Path(snapshot_dir).resolve()
    manifest_path = snapshot_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or manifest.get("format_version") != 1:
        raise ValueError(f"Unsupported migration snapshot format: {manifest_path}")
    entries = manifest.get("files")
    if not isinstance(entries, list):
        raise ValueError(f"Invalid migration snapshot manifest: {manifest_path}")

    restore_actions = []
    seen_paths = set()
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("existed"), bool):
            raise ValueError(f"Invalid file entry in migration snapshot: {manifest_path}")
        path = _absolute_path(entry.get("path", ""))
        if path in seen_paths:
            raise ValueError(f"Duplicate file in migration snapshot: {path}")
        seen_paths.add(path)
        if not entry["existed"]:
            restore_actions.append((path, None, None))
            continue

        relative_snapshot = Path(entry.get("snapshot", ""))
        if relative_snapshot.is_absolute() or ".." in relative_snapshot.parts:
            raise ValueError(f"Unsafe snapshot file path: {relative_snapshot}")
        snapshot_file = (snapshot_dir / relative_snapshot).resolve()
        try:
            snapshot_file.relative_to(snapshot_dir)
        except ValueError as error:
            raise ValueError(
                f"Snapshot file escapes its snapshot directory: {snapshot_file}"
            ) from error
        contents = snapshot_file.read_bytes()
        if hashlib.sha256(contents).hexdigest() != entry.get("sha256"):
            raise ValueError(f"Migration snapshot checksum mismatch: {snapshot_file}")
        mode = entry.get("mode")
        if not isinstance(mode, int) or isinstance(mode, bool) or mode < 0 or mode > 0o777:
            raise ValueError(f"Invalid saved file mode in migration snapshot: {snapshot_file}")
        restore_actions.append((path, contents, mode))

    for path, contents, mode in restore_actions:
        if contents is None:
            if path.is_symlink():
                raise ValueError(f"Refusing to remove a symlink during migration rollback: {path}")
            path.unlink(missing_ok=True)
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.restore.", dir=path.parent)
        try:
            with os.fdopen(fd, "wb") as destination:
                destination.write(contents)
                destination.flush()
                os.fsync(destination.fileno())
            os.chmod(temporary_name, mode)
            os.replace(temporary_name, path)
        except Exception:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass
            raise


def _schema_version(config: dict) -> int:
    value = config.get(SCHEMA_VERSION_KEY, 0)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"Invalid configuration schema version: {value!r}")
    if value > LATEST_SCHEMA_VERSION:
        raise ValueError(
            f"Configuration schema version {value} is newer than supported "
            f"version {LATEST_SCHEMA_VERSION}"
        )
    return value


def migrate_config(
    config_path: Path,
    backup_dir: Path,
    *,
    snapshot_paths: Iterable[str | Path] = (),
    snapshot_dir: Path | None = None,
) -> int:
    """Apply each pending schema migration once and restore bytes on failure.

    ``snapshot_paths`` lets a larger installer transaction include secrets,
    path metadata, and a rewritten job index in the same rollback point.
    Callers that already made that transaction snapshot can pass ``snapshot_dir``.
    """
    config_path = _absolute_path(config_path)
    if not config_path.is_file():
        raise FileNotFoundError(f"Configuration file does not exist: {config_path}")
    try:
        original_config = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"Invalid JSON configuration in {config_path}: {error}") from error
    if not isinstance(original_config, dict):
        raise ValueError(f"Expected a JSON object in {config_path}")
    current_version = _schema_version(original_config)
    if current_version == LATEST_SCHEMA_VERSION:
        return current_version

    paths = [config_path, *snapshot_paths]
    if snapshot_dir is None:
        snapshot_dir = create_snapshot(paths, backup_dir)
    else:
        snapshot_dir = Path(snapshot_dir)

    try:
        migrated_config = original_config
        while current_version < LATEST_SCHEMA_VERSION:
            migrated_config = MIGRATIONS[current_version](migrated_config)
            if not isinstance(migrated_config, dict):
                raise ValueError(
                    f"Migration to schema {current_version + 1} did not return an object"
                )
            current_version += 1
            migrated_config[SCHEMA_VERSION_KEY] = current_version
        _atomic_write(
            config_path,
            json.dumps(migrated_config, indent=2, ensure_ascii=False) + "\n",
            stat.S_IMODE(config_path.stat().st_mode),
        )
    except Exception:
        restore_snapshot(snapshot_dir)
        raise
    return current_version
