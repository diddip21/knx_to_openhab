#!/usr/bin/env python3
"""Build a deterministic, source-only release archive and SHA-256 checksum."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import os
import re
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path, PurePosixPath
from typing import Iterable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SEMVER_PATTERN = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
    r"(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$"
)
EXCLUDED_TOP_LEVEL = {
    ".git",
    ".github",
    ".pytest_cache",
    ".superpowers",
    ".venv",
    "openhab",
    "test-results",
    "tests",
    "var",
    "venv",
}
EXCLUDED_NAMES = {
    ".coverage",
    ".env",
    "Dockerfile.test",
    "pytest.ini",
    "requirements-dev.txt",
    "secrets.env",
}


class ReleaseArtifactError(ValueError):
    """Raised when release metadata or source files cannot be packaged safely."""


def validate_semver(version: str) -> str:
    """Return a strict SemVer 2.0 version or raise a helpful error."""
    match = SEMVER_PATTERN.fullmatch(version)
    if not match:
        raise ReleaseArtifactError(f"Invalid semantic version: {version!r}")
    prerelease = match.group(4)
    if prerelease:
        for identifier in prerelease.split("."):
            if identifier.isdigit() and len(identifier) > 1 and identifier.startswith("0"):
                raise ReleaseArtifactError(
                    f"Numeric prerelease identifiers must not have leading zeroes: {identifier}"
                )
    return version


def validate_tag(tag: str, expected_version: str | None = None) -> str:
    """Validate the project's ``v<semver>`` tag convention."""
    if not tag.startswith("v"):
        raise ReleaseArtifactError(f"Release tag must start with v: {tag!r}")
    version = validate_semver(tag[1:])
    if expected_version is not None and version != validate_semver(expected_version):
        raise ReleaseArtifactError(
            f"Release tag version {version} does not match VERSION file {expected_version}"
        )
    return version


def _is_excluded(relative_path: PurePosixPath) -> bool:
    parts = relative_path.parts
    basename = relative_path.name
    if not parts or parts[0] in EXCLUDED_TOP_LEVEL or basename in EXCLUDED_NAMES:
        return True
    if parts[:2] == ("docs", "screenshots"):
        return True
    if any(part in {"__pycache__", "node_modules"} for part in parts):
        return True
    if basename.startswith("test_") or basename.endswith("_test.py"):
        return True
    if basename.casefold().endswith((".knxproj", ".knxprojarchive")):
        return True
    if basename.casefold().endswith((".pyc", ".pyo", ".log")):
        return True
    return False


def _tracked_files(repo_root: Path) -> Iterable[tuple[PurePosixPath, int]]:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), "ls-files", "--stage", "-z"],
            check=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        raise ReleaseArtifactError(
            f"Could not list tracked release source files: {error}"
        ) from error

    for entry in result.stdout.split(b"\0"):
        if not entry:
            continue
        try:
            metadata, path_bytes = entry.split(b"\t", 1)
            mode_text, _object_id, stage_text = metadata.decode("ascii").split()
            relative_path = PurePosixPath(os.fsdecode(path_bytes))
            if stage_text != "0":
                raise ReleaseArtifactError(
                    f"Git index has unresolved merge entries: {relative_path}"
                )
            if relative_path.is_absolute() or ".." in relative_path.parts:
                raise ReleaseArtifactError(f"Unsafe tracked path in release: {relative_path}")
            if not _is_excluded(relative_path):
                yield relative_path, int(mode_text, 8)
        except (UnicodeDecodeError, ValueError) as error:
            if isinstance(error, ReleaseArtifactError):
                raise
            raise ReleaseArtifactError(f"Could not parse Git index entry {entry!r}") from error


def _archive_info(name: str, mode: int, size: int = 0) -> tarfile.TarInfo:
    info = tarfile.TarInfo(name)
    info.mode = mode
    info.uid = 0
    info.gid = 0
    info.uname = ""
    info.gname = ""
    info.mtime = 0
    info.size = size
    return info


def _release_file_list(repo_root: Path) -> list[tuple[PurePosixPath, int]]:
    files = sorted(_tracked_files(repo_root), key=lambda item: item[0].as_posix())
    if not files:
        raise ReleaseArtifactError(f"No tracked application source files found in {repo_root}")
    return files


def _write_archive(repo_root: Path, version: str, archive_path: Path) -> None:
    prefix = f"knx_to_openhab-{version}"
    files = _release_file_list(repo_root)
    with archive_path.open("wb") as raw_archive:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw_archive, mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT) as archive:
                root_info = _archive_info(prefix, 0o755)
                root_info.type = tarfile.DIRTYPE
                archive.addfile(root_info)
                for relative_path, git_mode in files:
                    source_path = repo_root.joinpath(*relative_path.parts)
                    archive_name = f"{prefix}/{relative_path.as_posix()}"
                    if not source_path.exists() and not source_path.is_symlink():
                        raise ReleaseArtifactError(
                            f"Tracked release file is missing: {relative_path}"
                        )
                    if git_mode == 0o120000:
                        target = os.readlink(source_path)
                        if os.path.isabs(target):
                            raise ReleaseArtifactError(
                                f"Absolute symlink is not safe to package: {relative_path}"
                            )
                        resolved_target = (source_path.parent / target).resolve(strict=False)
                        try:
                            resolved_target.relative_to(repo_root)
                        except ValueError as error:
                            raise ReleaseArtifactError(
                                f"Symlink escapes source tree: {relative_path}"
                            ) from error
                        info = _archive_info(archive_name, 0o777)
                        info.type = tarfile.SYMTYPE
                        info.linkname = target
                        archive.addfile(info)
                        continue
                    if not source_path.is_file():
                        raise ReleaseArtifactError(
                            f"Unsupported release source type: {relative_path}"
                        )
                    mode = 0o755 if git_mode == 0o100755 else 0o644
                    size = source_path.stat().st_size
                    with source_path.open("rb") as source:
                        archive.addfile(_archive_info(archive_name, mode, size), source)


def build_release(repo_root: Path, version: str, output_dir: Path) -> tuple[Path, Path]:
    """Build a reproducible source archive and standard sha256sum sidecar."""
    version = validate_semver(version)
    repo_root = Path(repo_root).resolve()
    output_dir = Path(output_dir)
    version_file = repo_root / "VERSION"
    try:
        configured_version = version_file.read_text(encoding="ascii").strip()
    except OSError as error:
        raise ReleaseArtifactError(f"Cannot read version source {version_file}: {error}") from error
    validate_semver(configured_version)
    if version != configured_version:
        raise ReleaseArtifactError(
            f"Requested release version {version} does not match VERSION file {configured_version}"
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    archive_path = output_dir / f"knx_to_openhab-{version}.tar.gz"
    checksum_path = output_dir / f"{archive_path.name}.sha256"
    temporary_archive: Path | None = None
    temporary_checksum: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=output_dir, prefix=f".{archive_path.name}.", delete=False
        ) as tmp:
            temporary_archive = Path(tmp.name)
        _write_archive(repo_root, version, temporary_archive)
        digest = hashlib.sha256(temporary_archive.read_bytes()).hexdigest()

        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="ascii",
            dir=output_dir,
            prefix=f".{checksum_path.name}.",
            delete=False,
        ) as tmp:
            temporary_checksum = Path(tmp.name)
            tmp.write(f"{digest}  {archive_path.name}\n")

        os.replace(temporary_archive, archive_path)
        temporary_archive = None
        os.replace(temporary_checksum, checksum_path)
        temporary_checksum = None
    finally:
        for temporary in (temporary_archive, temporary_checksum):
            if temporary is not None:
                temporary.unlink(missing_ok=True)
    return archive_path, checksum_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True, help="SemVer version without the v tag prefix")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        archive, checksum = build_release(PROJECT_ROOT, args.version, args.output_dir)
    except ReleaseArtifactError as error:
        print(f"Release build failed: {error}", file=sys.stderr)
        return 2
    print(archive)
    print(checksum)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
