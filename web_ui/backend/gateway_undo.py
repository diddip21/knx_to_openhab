"""Durable, single-level undo snapshots for live KNX gateway changes."""

import base64
import binascii
import json
import os
import re
import stat
from collections.abc import Mapping
from typing import Any

from .storage import save_json_atomic

SNAPSHOT_VERSION = 2
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _validate_snapshot(snapshot: Any) -> dict[str, Any]:
    if not isinstance(snapshot, dict):
        raise ValueError("Invalid KNX gateway undo snapshot")
    version = snapshot.get("version")
    if type(version) is not int or version not in (1, SNAPSHOT_VERSION):
        raise ValueError("Invalid KNX gateway undo snapshot")
    if not isinstance(snapshot.get("job_id"), str) or not snapshot["job_id"]:
        raise ValueError("Invalid KNX gateway undo snapshot job ID")
    required_strings = (
        "file_content_b64",
        "previous_gateway_override",
        "openhab_root",
        "managed_path",
        "things_format",
        "post_change_sha256",
    )
    if any(not isinstance(snapshot.get(key), str) for key in required_strings):
        raise ValueError("Invalid KNX gateway undo snapshot")
    if version == SNAPSHOT_VERSION and (
        not isinstance(snapshot.get("deployment_id"), str) or not snapshot["deployment_id"]
    ):
        raise ValueError("Invalid KNX gateway undo snapshot deployment ID")
    if snapshot["things_format"] not in ("dsl", "yaml"):
        raise ValueError("Invalid KNX gateway undo snapshot format")
    if not _SHA256.fullmatch(snapshot["post_change_sha256"]):
        raise ValueError("Invalid KNX gateway undo snapshot digest")
    try:
        base64.b64decode(snapshot["file_content_b64"], validate=True)
    except (binascii.Error, ValueError) as error:
        raise ValueError("Invalid KNX gateway undo snapshot content") from error
    return snapshot


def load_snapshot(path: str) -> dict[str, Any] | None:
    """Read and validate the persisted snapshot without following a symlink."""
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except FileNotFoundError:
        return None
    with os.fdopen(descriptor, "r", encoding="utf-8") as snapshot_file:
        if not stat.S_ISREG(os.fstat(snapshot_file.fileno()).st_mode):
            raise ValueError("KNX gateway undo snapshot is not a regular file")
        try:
            snapshot = json.load(snapshot_file)
        except (json.JSONDecodeError, UnicodeError) as error:
            raise ValueError("Invalid KNX gateway undo snapshot JSON") from error
    return _validate_snapshot(snapshot)


def save_snapshot(path: str, snapshot: Mapping[str, Any]) -> None:
    """Atomically replace the durable snapshot after validating its schema."""
    data = dict(snapshot)
    data.setdefault("version", SNAPSHOT_VERSION)
    _validate_snapshot(data)
    save_json_atomic(path, data)


def clear_snapshot(path: str) -> None:
    """Remove the active snapshot, if one exists."""
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass
