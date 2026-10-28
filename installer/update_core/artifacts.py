"""Bounded release metadata, archives and stopped output; no candidate execution."""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import re
import stat
import tarfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

from .protocol import Limits, ReleaseContract, parse_contract

_SEMVER = re.compile(
    r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
    r"(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
)
REPOSITORY = "diddip21/knx_to_openhab"
# Only download adapters may follow redirects, and only to these exact hosts.
APPROVED_REDIRECT_HOSTS = frozenset(
    {
        "api.github.com",
        "github.com",
        "release-assets.githubusercontent.com",
        "objects.githubusercontent.com",
    }
)


@dataclass(frozen=True)
class ReleaseInfo:
    version: str
    tag: str
    archive_name: str
    archive_url: str
    checksum_url: str


def _precedence(version: str) -> tuple:
    if not isinstance(version, str) or len(version) > 256:
        raise ValueError("Invalid semantic version")
    match = _SEMVER.fullmatch(version)
    if match is None:
        raise ValueError(f"Invalid semantic version: {version!r}")
    pre = match[4]
    identifiers = []
    if pre:
        for part in pre.split("."):
            if part.isdigit():
                if len(part) > 1 and part[0] == "0":
                    raise ValueError("Numeric prerelease identifier has leading zeroes")
                identifiers.append((0, int(part)))
            else:
                identifiers.append((1, part))
    return (int(match[1]), int(match[2]), int(match[3]), pre is None, tuple(identifiers))


def _asset_url(url: object, version: str, name: str) -> str:
    expected_path = f"/{REPOSITORY}/releases/download/v{version}/{name}"
    if not isinstance(url, str) or any(ord(char) <= 32 or ord(char) == 127 for char in url):
        raise ValueError("Invalid release asset URL")
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.netloc != "github.com"
        or parsed.path != expected_path
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Unsafe release asset URL")
    return url


def _release_info(release: dict, version: str) -> ReleaseInfo:
    name = f"knx_to_openhab-{version}.tar.gz"
    assets = release.get("assets")
    if not isinstance(assets, list):
        raise ValueError("Missing release assets")
    found = {}
    seen = set()
    for asset in assets:
        if not isinstance(asset, dict) or not isinstance(asset.get("name"), str):
            raise ValueError("Malformed release asset")
        asset_name = asset["name"]
        if asset_name in seen:
            raise ValueError("Duplicate release asset")
        seen.add(asset_name)
        if asset_name in (name, name + ".sha256"):
            found[asset_name] = _asset_url(asset.get("browser_download_url"), version, asset_name)
    if set(found) != {name, name + ".sha256"}:
        raise ValueError("Missing required release assets")
    return ReleaseInfo(version, f"v{version}", name, found[name], found[name + ".sha256"])


def select_release(metadata: object, channel: str, current: str) -> ReleaseInfo | None:
    """Select a strictly newer release from a latest object or bounded listing.

    A listing is either a flat release list or a list of page lists, in HTTP order.
    The HTTP adapter must also bound raw bytes before decoding; this function
    independently bounds the decoded aggregate. Each channel selects only its own
    release kind; metadata flags must agree with semantic prerelease identifiers.
    Missing assets on the selected release fail closed.
    """
    if channel not in ("stable", "prerelease"):
        raise ValueError("Unsupported update channel")
    current_key = _precedence(current)
    try:
        size = len(json.dumps(metadata, ensure_ascii=False, allow_nan=False).encode("utf-8"))
    except (TypeError, ValueError, RecursionError, UnicodeError) as error:
        raise ValueError("Invalid release metadata") from error
    if size > Limits.METADATA_BYTES:
        raise ValueError("Release metadata exceeds byte limit")
    if isinstance(metadata, dict):
        releases = [metadata]
    elif isinstance(metadata, list):
        if metadata and isinstance(metadata[0], list):
            if len(metadata) > Limits.METADATA_PAGES or not all(
                isinstance(page, list) for page in metadata
            ):
                raise ValueError("Invalid or excessive metadata pages")
            releases = [release for page in metadata for release in page]
        else:
            releases = metadata
    else:
        raise ValueError("Expected release metadata object or list")
    candidates = []
    for release in releases:
        if not isinstance(release, dict):
            raise ValueError("Malformed release metadata")
        if type(release.get("draft")) is not bool or type(release.get("prerelease")) is not bool:
            raise ValueError("Missing or invalid release flags")
        tag = release.get("tag_name")
        if not isinstance(tag, str) or not tag.startswith("v"):
            raise ValueError("Expected a v-prefixed semantic version tag")
        version = tag[1:]
        key = _precedence(version)
        is_prerelease = not key[3]
        if release["prerelease"] != is_prerelease:
            raise ValueError("Release prerelease flag disagrees with semantic version")
        if release["draft"] or is_prerelease != (channel == "prerelease"):
            continue
        if key > current_key:
            candidates.append((key, version, release))
    if not candidates:
        return None
    _, version, selected = max(candidates, key=lambda candidate: candidate[0])
    return _release_info(selected, version)


def validate_download_url(url: str) -> str:
    """Validate every redirect *before* making a request; no ambient proxy support."""
    if not isinstance(url, str) or any(ord(c) <= 32 or ord(c) == 127 for c in url):
        raise ValueError("Unsafe download URL")
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.netloc not in APPROVED_REDIRECT_HOSTS or parsed.fragment:
        raise ValueError("Unapproved download host")
    return url


def _check_release(release: ReleaseInfo) -> None:
    _precedence(release.version)
    if release.tag != f"v{release.version}" or release.archive_name != (
        f"knx_to_openhab-{release.version}.tar.gz"
    ):
        raise ValueError("Inconsistent release identity")
    _asset_url(release.archive_url, release.version, release.archive_name)
    _asset_url(release.checksum_url, release.version, release.archive_name + ".sha256")


def verify_archive_bytes(data: bytes, checksum: bytes, release: ReleaseInfo) -> None:
    """Pure checksum boundary, also useful for portable corruption tests."""
    _check_release(release)
    if not data or len(data) > Limits.ARCHIVE_BYTES or len(checksum) > Limits.CHECKSUM_BYTES:
        raise ValueError("Archive or checksum exceeds limit")
    match = re.fullmatch(
        rb"([0-9a-fA-F]{64}) [ *]" + re.escape(release.archive_name.encode("ascii")) + rb"\n?",
        checksum,
    )
    if match is None or hashlib.sha256(data).hexdigest() != match[1].decode().lower():
        raise ValueError("Invalid archive checksum")


def verify_archive(archive: Path, checksum: bytes, release: ReleaseInfo) -> None:
    """Parent verifies only its protected copy, never child-owned pathname data."""
    from .secure_fs import read_regular

    verify_archive_bytes(read_regular(archive, Limits.ARCHIVE_BYTES), checksum, release)


def _archive_path(name: str) -> PurePosixPath:
    path = PurePosixPath(name)
    if (
        not name
        or name.startswith("/")
        or "\\" in name
        or any(ord(c) < 32 or ord(c) == 127 for c in name)
        or any(p in ("", ".", "..") for p in name.rstrip("/").split("/"))
        or len(path.parts) > Limits.TREE_DEPTH
        or len(name) > 4096
    ):
        raise ValueError("Unsafe archive path")
    return path


def extract_archive(archive: Path, root: Path, release: ReleaseInfo) -> None:
    """Unprivileged-only caller: manually copy regular entries, never tar.extract.

    Archive is the coordinator's root-owned verified copy, exposed read-only by
    the sandbox. Strip exactly the release builder's versioned top-level directory.
    root is a freshly reserved empty candidate; on any failure retain evidence.
    """
    _check_release(release)
    if archive.stat().st_size > Limits.ARCHIVE_BYTES:
        raise ValueError("Compressed archive exceeds limit")
    root.mkdir(mode=0o700, exist_ok=True)
    if any(root.iterdir()):
        raise ValueError("Extraction destination must be empty")
    seen = set()
    nodes = set()
    total = 0
    try:
        # tarfile stops at the tar end marker without checking the gzip trailer.
        # Independently consume the bounded stream to reject truncation/CRC errors
        # and compressed padding bombs, without allocating the expanded archive.
        expanded = 0
        with gzip.open(archive, "rb") as compressed:
            while chunk := compressed.read(65536):
                expanded += len(chunk)
                if expanded > Limits.TREE_BYTES + Limits.TREE_ENTRIES * 2048 + 10240:
                    raise ValueError("Archive stream exceeds expansion limit")
        with tarfile.open(archive, "r:gz") as source:
            for entry in source:
                path = _archive_path(entry.name)
                if path.parts[0] != f"knx_to_openhab-{release.version}":
                    raise ValueError("Unexpected archive top-level directory")
                name = str(path)
                if (
                    name in seen
                    or entry.mode & 0o7022
                    or entry.sparse is not None
                    or any("sparse" in key.lower() for key in entry.pax_headers)
                    or not (entry.isdir() or entry.isreg())
                ):
                    raise ValueError("Unsafe or duplicate archive entry")
                seen.add(name)
                if len(path.parts) == 1:
                    if not entry.isdir():
                        raise ValueError("Expected release root directory")
                    continue
                path = PurePosixPath(*path.parts[1:])
                name = str(path)
                nodes.update(str(parent) for parent in path.parents if str(parent) != ".")
                nodes.add(name)
                if len(nodes) + 1 > Limits.TREE_ENTRIES:
                    raise ValueError("Archive exceeds entry limit")
                total += entry.size
                if entry.size < 0 or entry.size > Limits.FILE_BYTES or total > Limits.TREE_BYTES:
                    raise ValueError("Archive exceeds expansion limit")
                destination = root.joinpath(*path.parts)
                destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                if entry.isdir():
                    destination.mkdir(mode=0o700, exist_ok=True)
                else:
                    stream = source.extractfile(entry)
                    if stream is None:
                        raise ValueError("Missing archive payload")
                    remaining = entry.size
                    with stream, destination.open("xb") as output:
                        while remaining:
                            chunk = stream.read(min(65536, remaining))
                            if not chunk:
                                raise ValueError("Truncated archive")
                            output.write(chunk)
                            remaining -= len(chunk)
                    destination.chmod(0o700 if entry.mode & 0o111 else 0o600)
    except (tarfile.TarError, EOFError, OSError) as error:
        raise ValueError("Invalid release archive") from error
    try:
        if (root / "VERSION").read_bytes().strip() != release.version.encode("ascii"):
            raise ValueError("Release VERSION mismatch")
        parse_contract((root / "installer/update_contract.json").read_bytes())
    except OSError as error:
        raise ValueError("Incomplete release layout") from error


def _read_entry(entry, max_bytes):
    if entry.info.st_size > max_bytes:
        raise ValueError("Child output exceeds byte limit")
    result = bytearray()
    while len(result) <= max_bytes:
        data = os.read(entry.fd, min(65536, max_bytes + 1 - len(result)))
        if not data:
            break
        result.extend(data)
    entry.check()
    after = os.fstat(entry.fd)
    if len(result) > max_bytes or (after.st_size, after.st_mtime_ns, after.st_ctime_ns) != (
        entry.info.st_size,
        entry.info.st_mtime_ns,
        entry.info.st_ctime_ns,
    ):
        raise ValueError("Oversized or raced child output")
    return bytes(result)


def ingest_child_file(
    output: Path, name: str, max_bytes: int, expected_uid: int, *, stopped: bool
) -> bytes:
    """Narrow stopped-cgroup ingestion anchored in the trusted workspace parent.

    Only one direct output filename is accepted; do not weaken root-only
    secure_fs.read_regular. Caller must obtain stopped=True from successful
    SystemdAdapter teardown, never from a child marker or its exit code.
    """
    from . import secure_fs as fs

    if stopped is not True:
        raise ValueError("Child cgroup must be stopped before ingestion")
    if (
        not name
        or name in (".", "..")
        or "/" in name
        or "\\" in name
        or type(max_bytes) is not int
        or max_bytes < 0
        or type(expected_uid) is not int
        or expected_uid < 0
    ):
        raise ValueError("Invalid child ingestion parameters")
    with fs._parent(output) as (stack, parent, directory, chain):
        root = fs._open(
            stack, parent, directory, {expected_uid}, os.fstat(parent).st_dev, directory=True
        )
        entry = fs._open(stack, root.fd, name, {expected_uid}, root.info.st_dev)
        data = _read_entry(entry, max_bytes)
        fs._check([*chain, root, entry])
        return data


def validate_extracted_tree(
    root: Path, release: ReleaseInfo, *, expected_uid: int = 0
) -> ReleaseContract:
    """Independently validate a stopped tree (root-owned by default).

    freeze_tree also bounds the COMPLETE post-dependency tree *before* retaining
    too many FDs or changing ownership. Do not validate child output by pathlib.
    expected_uid permits pre-dependency inspection without transferring ownership
    twice. It must come from the protected worker identity, never child output.
    """
    from . import secure_fs as fs

    _check_release(release)
    if type(expected_uid) is not int or expected_uid < 0:
        raise ValueError("Invalid preparation owner")
    with fs._parent(root) as (stack, parent, name, chain):
        entries = fs._tree(stack, parent, name, {expected_uid})
        base = entries[-1]
        files = {}
        for entry in entries:
            if stat.S_ISREG(entry.info.st_mode):
                parts = [ancestor.name for ancestor in entry.ancestors[1:]] + [entry.name]
                files["/".join(parts)] = entry
        required = {
            "VERSION",
            "requirements.txt",
            "installer/config_migrations.py",
            "installer/update_contract.json",
        }
        if not required <= files.keys():
            raise ValueError("Incomplete release layout")
        if _read_entry(files["VERSION"], 256).strip() != release.version.encode("ascii"):
            raise ValueError("Release VERSION mismatch")
        contract = parse_contract(
            _read_entry(files["installer/update_contract.json"], Limits.CONFIG_BYTES)
        )
        fs._check([*chain, base, *entries])
        return contract
