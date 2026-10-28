"""Pure release metadata selection; no HTTP or candidate-code execution."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from urllib.parse import urlsplit

from .protocol import Limits

_SEMVER = re.compile(
    r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
    r"(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
)
REPOSITORY = "diddip21/knx_to_openhab"
# Only download adapters may follow redirects, and only to these exact hosts.
APPROVED_REDIRECT_HOSTS = frozenset({"github.com", "release-assets.githubusercontent.com"})


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
    independently bounds the decoded aggregate. Prerelease opts into prereleases
    as well as stable releases. Missing assets on the selected release fail closed.
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
        if release["draft"] or (channel == "stable" and (release["prerelease"] or not key[3])):
            continue
        if key > current_key:
            candidates.append((key, version, release))
    if not candidates:
        return None
    _, version, selected = max(candidates, key=lambda candidate: candidate[0])
    return _release_info(selected, version)
