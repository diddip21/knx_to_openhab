#!/usr/bin/env python3
"""Download, verify, and safely extract one published KNX to OpenHAB release."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import tarfile
import tempfile
from datetime import datetime
from pathlib import Path, PurePosixPath
from urllib.error import URLError
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen

_STABLE_TAG = re.compile(
    r"^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$"
)
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_SHA256_LINE = re.compile(r"^([0-9a-f]{64})  ([A-Za-z0-9_.+-]+)$")
_DOWNLOAD_LIMIT = 256 * 1024 * 1024
_EXPANDED_LIMIT = 1024 * 1024 * 1024
_DOWNLOAD_HOSTS = {
    "github.com",
    "objects.githubusercontent.com",
    "release-assets.githubusercontent.com",
}
_CHUNK_SIZE = 1024 * 1024


class ReleasePreparationError(ValueError):
    """Raised when a release asset cannot be trusted or staged safely."""


def _release_version(tag: str) -> str:
    match = _STABLE_TAG.fullmatch(tag)
    if not match:
        raise ReleasePreparationError(f"A stable SemVer release tag is required: {tag!r}")
    return tag[1:]


def _validate_metadata(
    repository: str,
    tag: str,
    commit_hash: str,
    commit_date: str,
    commit_message: str,
    author: str,
) -> dict[str, str]:
    version = _release_version(tag)
    if not _REPOSITORY.fullmatch(repository):
        raise ReleasePreparationError("Repository must use owner/name form")
    if not _COMMIT.fullmatch(commit_hash):
        raise ReleasePreparationError("Release commit hash must be a 40-character SHA-1")
    if not commit_date or len(commit_date) > 80:
        raise ReleasePreparationError("Release commit date is missing or invalid")
    try:
        datetime.fromisoformat(commit_date.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as error:
        raise ReleasePreparationError("Release commit date is missing or invalid") from error
    if len(commit_message) > 500 or len(author) > 200:
        raise ReleasePreparationError("Release commit metadata is too long")
    return {
        "version": version,
        "release_tag": tag,
        "commit_hash": commit_hash,
        "commit_short": commit_hash[:7],
        "commit_date": commit_date,
        "commit_message": commit_message.splitlines()[0] if commit_message else "No message",
        "author": author or "unknown",
        "repository": f"https://github.com/{repository}",
        "branch": tag,
    }


def _download(url: str, destination: Path, *, limit: int = _DOWNLOAD_LIMIT) -> None:
    request = Request(url, headers={"User-Agent": "knx-to-openhab-updater"})
    try:
        with urlopen(request, timeout=30) as response:
            final_url = urlsplit(response.geturl())
            if final_url.scheme != "https" or final_url.hostname not in _DOWNLOAD_HOSTS:
                raise ReleasePreparationError("Release download redirected to an untrusted host")
            content_length = response.headers.get("Content-Length")
            if content_length and int(content_length) > limit:
                raise ReleasePreparationError("Release asset exceeds the download size limit")
            total = 0
            with destination.open("xb") as output:
                while chunk := response.read(_CHUNK_SIZE):
                    total += len(chunk)
                    if total > limit:
                        raise ReleasePreparationError(
                            "Release asset exceeds the download size limit"
                        )
                    output.write(chunk)
                output.flush()
                os.fsync(output.fileno())
    except (OSError, URLError, ValueError) as error:
        destination.unlink(missing_ok=True)
        if isinstance(error, ReleasePreparationError):
            raise
        raise ReleasePreparationError(f"Could not download release asset: {error}") from error


def _verify_checksum(archive_path: Path, checksum_path: Path, expected_name: str) -> None:
    try:
        sidecar = checksum_path.read_bytes()
        if len(sidecar) > 1024:
            raise ReleasePreparationError("Release checksum file is unexpectedly large")
        line = sidecar.decode("ascii").strip("\r\n")
    except (OSError, UnicodeDecodeError) as error:
        raise ReleasePreparationError(f"Could not read release checksum: {error}") from error

    match = _SHA256_LINE.fullmatch(line)
    if not match or match.group(2) != expected_name:
        raise ReleasePreparationError("Release checksum file has an unexpected format or filename")

    digest = hashlib.sha256()
    try:
        with archive_path.open("rb") as archive_file:
            while chunk := archive_file.read(_CHUNK_SIZE):
                digest.update(chunk)
    except OSError as error:
        raise ReleasePreparationError(f"Could not read release archive: {error}") from error
    if digest.hexdigest() != match.group(1):
        raise ReleasePreparationError("Release archive SHA-256 does not match its sidecar")


def _safe_extract(archive_path: Path, app_dir: Path, root_name: str) -> None:
    if app_dir.exists() or app_dir.is_symlink():
        raise ReleasePreparationError(f"Release staging path already exists: {app_dir}")
    app_dir.mkdir(mode=0o750)
    seen: set[str] = set()
    expanded_size = 0
    root_seen = False
    try:
        with tarfile.open(archive_path, mode="r:gz") as archive:
            for member in archive:
                raw_name = member.name
                path = PurePosixPath(raw_name)
                if (
                    not raw_name
                    or "\\" in raw_name
                    or path.is_absolute()
                    or ".." in path.parts
                    or path.as_posix() != raw_name.rstrip("/")
                    or not path.parts
                    or path.parts[0] != root_name
                ):
                    raise ReleasePreparationError(f"Unsafe release archive path: {raw_name!r}")
                normalized_name = path.as_posix()
                if normalized_name in seen:
                    raise ReleasePreparationError(f"Duplicate release archive path: {raw_name}")
                seen.add(normalized_name)
                if len(path.parts) == 1:
                    if not member.isdir():
                        raise ReleasePreparationError("Release archive root must be a directory")
                    root_seen = True
                    continue

                relative = PurePosixPath(*path.parts[1:])
                target = app_dir.joinpath(*relative.parts)
                try:
                    target.relative_to(app_dir)
                except ValueError as error:
                    raise ReleasePreparationError(
                        f"Release path escapes staging: {raw_name}"
                    ) from error

                if member.isdir():
                    if target.exists() and not target.is_dir():
                        raise ReleasePreparationError(
                            f"Release path collides with a file: {raw_name}"
                        )
                    target.mkdir(mode=0o750, parents=True, exist_ok=True)
                    continue
                if not member.isfile():
                    raise ReleasePreparationError(f"Unsupported release archive entry: {raw_name}")
                expanded_size += member.size
                if member.size < 0 or expanded_size > _EXPANDED_LIMIT:
                    raise ReleasePreparationError("Expanded release archive exceeds the size limit")

                target.parent.mkdir(mode=0o750, parents=True, exist_ok=True)
                if target.exists() or target.is_symlink():
                    raise ReleasePreparationError(f"Duplicate release file path: {raw_name}")
                source = archive.extractfile(member)
                if source is None:
                    raise ReleasePreparationError(
                        f"Could not read release archive file: {raw_name}"
                    )
                with source, target.open("xb") as output:
                    shutil.copyfileobj(source, output, _CHUNK_SIZE)
                target.chmod(0o755 if member.mode & 0o111 else 0o644)

        if not root_seen:
            raise ReleasePreparationError(f"Release archive is missing its {root_name} root")
        required_files = (
            "requirements.txt",
            "update.sh",
            "knxoh_paths.py",
            "installer/create_update_backup.py",
            "installer/prepare_release.py",
            "web_ui/backend/app.py",
            "installer/launch_web.sh",
        )
        for relative in required_files:
            required = app_dir / relative
            if not required.is_file() or required.is_symlink():
                raise ReleasePreparationError(
                    f"Release archive is missing required file: {relative}"
                )
    except (OSError, tarfile.TarError) as error:
        raise ReleasePreparationError(f"Could not extract release archive: {error}") from error


def verify_and_extract(
    archive_path: Path,
    checksum_path: Path,
    destination: Path,
    *,
    repository: str,
    tag: str,
    commit_hash: str,
    commit_date: str,
    commit_message: str,
    author: str,
) -> Path:
    """Verify a local release asset pair and extract it under a fresh destination."""
    metadata = _validate_metadata(repository, tag, commit_hash, commit_date, commit_message, author)
    destination = Path(destination)
    if destination.is_symlink():
        raise ReleasePreparationError("Release staging directory must not be a symlink")
    if destination.exists() and (not destination.is_dir() or any(destination.iterdir())):
        raise ReleasePreparationError("Release staging directory must be empty")
    destination.mkdir(parents=True, mode=0o750, exist_ok=True)

    version = metadata["version"]
    archive_name = f"knx_to_openhab-{version}.tar.gz"
    _verify_checksum(Path(archive_path), Path(checksum_path), archive_name)
    app_dir = destination / f"knx_to_openhab-{version}"
    try:
        _safe_extract(Path(archive_path), app_dir, app_dir.name)
        version_file = app_dir / "version.json"
        if version_file.is_symlink() or (version_file.exists() and not version_file.is_file()):
            raise ReleasePreparationError("Release version.json path is not a regular file")
        temporary_version = app_dir / ".version.json.tmp"
        with temporary_version.open("x", encoding="utf-8") as output:
            json.dump(metadata, output, ensure_ascii=False, indent=2)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary_version, version_file)
    except Exception:
        shutil.rmtree(app_dir, ignore_errors=True)
        raise
    return app_dir


def prepare_release(
    destination: Path,
    *,
    repository: str,
    tag: str,
    commit_hash: str,
    commit_date: str,
    commit_message: str,
    author: str,
) -> Path:
    """Download the published archive and checksum, then verify and extract them."""
    version = _release_version(tag)
    _validate_metadata(repository, tag, commit_hash, commit_date, commit_message, author)
    destination = Path(destination)
    if destination.is_symlink():
        raise ReleasePreparationError("Release staging directory must not be a symlink")
    if destination.exists() and (not destination.is_dir() or any(destination.iterdir())):
        raise ReleasePreparationError("Release staging directory must be empty")
    destination.mkdir(parents=True, mode=0o750, exist_ok=True)
    download_dir = Path(tempfile.mkdtemp(prefix=".assets-", dir=destination.parent))
    archive_name = f"knx_to_openhab-{version}.tar.gz"
    checksum_name = f"{archive_name}.sha256"
    encoded_tag = quote(tag, safe="")
    base_url = f"https://github.com/{repository}/releases/download/{encoded_tag}"
    archive_path = download_dir / archive_name
    checksum_path = download_dir / checksum_name
    try:
        _download(f"{base_url}/{quote(archive_name, safe='')}", archive_path)
        _download(f"{base_url}/{quote(checksum_name, safe='')}", checksum_path, limit=1024)
        return verify_and_extract(
            archive_path,
            checksum_path,
            destination,
            repository=repository,
            tag=tag,
            commit_hash=commit_hash,
            commit_date=commit_date,
            commit_message=commit_message,
            author=author,
        )
    finally:
        shutil.rmtree(download_dir, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--commit-hash", required=True)
    parser.add_argument("--commit-date", required=True)
    parser.add_argument("--commit-message", default="")
    parser.add_argument("--author", default="unknown")
    args = parser.parse_args(argv)
    try:
        app_dir = prepare_release(
            args.destination,
            repository=args.repository,
            tag=args.tag,
            commit_hash=args.commit_hash,
            commit_date=args.commit_date,
            commit_message=args.commit_message,
            author=args.author,
        )
    except (OSError, ReleasePreparationError) as error:
        print(f"Release preparation failed: {error}", file=sys.stderr)
        return 1
    print(app_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
