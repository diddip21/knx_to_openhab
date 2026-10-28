"""Pure, fail-closed protocol-1 request and copied-configuration validation."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID


class Limits:
    """Fixed resource budgets shared by the coordinator and its HTTP adapters.

    Small requests contain only three fields. Config and total metadata each get
    1 MiB; at most ten listing pages prevent unbounded release discovery. Every
    HTTP operation must use the 30-second timeout (including downloads).
    """

    REQUEST_BYTES = 4 * 1024
    CONFIG_BYTES = 1024 * 1024
    METADATA_BYTES = 1024 * 1024
    METADATA_PAGES = 10
    HTTP_TIMEOUT_SECONDS = 30
    MAX_VERSION = 2**31 - 1


@dataclass(frozen=True)
class UpdateRequest:
    format_version: int
    request_id: str
    channel: str


@dataclass(frozen=True)
class ReleaseContract:
    updater_protocol: int
    config_copy_protocol: int
    accepted_input_schema_versions: tuple[int, ...]
    output_schema_version: int
    runtime_backward_compatible: bool


@dataclass(frozen=True)
class Paths:
    """Protected release parent and activation link, not service-provided paths."""

    releases: Path
    current: Path


@dataclass(frozen=True)
class Journal:
    """Candidate provenance supplied only from the protected coordinator journal.

    Record device/inode immediately after exclusive reservation, before granting
    the preparation child access. Publication is sticky, even after rollback.
    This is the filesystem subset, not the future transaction state machine.
    """

    candidate: Path | None
    prior_target: Path
    candidate_identity: tuple[int, int] | None
    candidate_uid: int
    candidate_created: bool = False
    candidate_published: bool = False


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON field: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError(f"Invalid JSON constant: {value}")


def parse_object(raw: bytes, limit: int) -> dict:
    """Decode one bounded UTF-8 JSON object, rejecting duplicate keys and NaN."""
    if not isinstance(raw, bytes) or len(raw) > limit:
        raise ValueError("JSON input exceeds its byte limit")
    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except (UnicodeError, RecursionError) as error:
        raise ValueError("Invalid JSON input") from error
    if not isinstance(value, dict):
        raise ValueError("Expected a JSON object")
    return value


def _version(value: object) -> int:
    if type(value) is not int or not 0 <= value <= Limits.MAX_VERSION:
        raise ValueError("Expected a bounded integer version")
    return value


def parse_request(raw: bytes) -> UpdateRequest:
    value = parse_object(raw, Limits.REQUEST_BYTES)
    if set(value) != {"format_version", "request_id", "channel"}:
        raise ValueError("Unexpected or missing request fields")
    if _version(value["format_version"]) != 1:
        raise ValueError("Unsupported request format")
    request_id = value["request_id"]
    if not isinstance(request_id, str):
        raise ValueError("Invalid request UUID")
    try:
        if str(UUID(request_id)) != request_id:
            raise ValueError("Request UUID must be canonical")
    except (ValueError, AttributeError) as error:
        raise ValueError("Invalid request UUID") from error
    if value["channel"] not in ("stable", "prerelease"):
        raise ValueError("Unsupported update channel")
    return UpdateRequest(1, request_id, value["channel"])


def parse_contract(raw: bytes) -> ReleaseContract:
    value = parse_object(raw, Limits.CONFIG_BYTES)
    if set(value) != set(ReleaseContract.__dataclass_fields__):
        raise ValueError("Unexpected or missing release contract fields")
    for key in ("updater_protocol", "config_copy_protocol"):
        if _version(value[key]) != 1:
            raise ValueError(f"Unsupported {key}")
    versions = value["accepted_input_schema_versions"]
    if not isinstance(versions, list) or not versions:
        raise ValueError("Expected accepted input schema versions")
    for version in versions:
        _version(version)
    if len(set(versions)) != len(versions):
        raise ValueError("Duplicate accepted schema versions")
    output = _version(value["output_schema_version"])
    if any(version > output for version in versions):
        raise ValueError("Schema downgrades are not supported")
    if value["runtime_backward_compatible"] is not True:
        raise ValueError("Explicit runtime backward compatibility is required")
    return ReleaseContract(1, 1, tuple(versions), output, True)


def _same_json(original: object, migrated: object) -> bool:
    # Python equality alone would silently accept True for 1, including in lists.
    if type(original) is not type(migrated):
        return False
    if isinstance(original, dict):
        return original.keys() == migrated.keys() and all(
            _same_json(value, migrated[key]) for key, value in original.items()
        )
    if isinstance(original, list):
        return len(original) == len(migrated) and all(
            _same_json(left, right) for left, right in zip(original, migrated)
        )
    return original == migrated


def validate_config_copy(original: dict, migrated: dict, contract: ReleaseContract) -> None:
    """Allow new top-level defaults and schema changes, never sibling-tree edits."""
    for config in (original, migrated):
        if not isinstance(config, dict):
            raise ValueError("Expected a configuration object")
        try:
            size = len(json.dumps(config, ensure_ascii=False, allow_nan=False).encode("utf-8"))
        except (TypeError, ValueError, RecursionError, UnicodeError) as error:
            raise ValueError("Invalid configuration JSON") from error
        if size > Limits.CONFIG_BYTES:
            raise ValueError("Configuration exceeds byte limit")
    input_version = _version(original.get("schema_version", 0))
    if input_version not in contract.accepted_input_schema_versions:
        raise ValueError("Unsupported input configuration schema")
    if _version(migrated.get("schema_version")) != contract.output_schema_version:
        raise ValueError("Unexpected output configuration schema")
    for key, value in original.items():
        if key != "schema_version" and (
            key not in migrated or not _same_json(value, migrated[key])
        ):
            raise ValueError(f"Migration changed existing configuration key: {key}")
