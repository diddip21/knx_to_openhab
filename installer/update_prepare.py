"""Root-installed unprivileged worker; never run/import this from a candidate.

The isolated system Python cannot find sibling modules by default. Only when
launched as the standalone installed script, add its fixed administrator-owned
directory, not cwd, current, application modules, or a candidate virtualenv.
"""

from __future__ import annotations

import argparse
import json
import os
import stat
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).absolute().parent))
    from update_core.artifacts import (
        REPOSITORY,
        ReleaseInfo,
        _check_release,
        extract_archive,
        validate_download_url,
    )
    from update_core.protocol import Limits, parse_object
else:
    from .update_core.artifacts import (
        REPOSITORY,
        ReleaseInfo,
        _check_release,
        extract_archive,
        validate_download_url,
    )
    from .update_core.protocol import Limits, parse_object


def _unprivileged():
    if not hasattr(os, "geteuid") or os.geteuid() == 0:
        raise ValueError("Preparation must run unprivileged")


class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_download_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def download(url: str, limit: int) -> bytes:
    """Bound every response, redirects, declared length and total operation time."""
    validate_download_url(url)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), SafeRedirect())
    started = time.monotonic()
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/vnd.github+json", "User-Agent": "knxoh-release-updater/1"},
    )
    with opener.open(request, timeout=Limits.HTTP_TIMEOUT_SECONDS) as response:
        validate_download_url(response.geturl())
        length = response.headers.get("Content-Length")
        if length is not None and (not length.isdigit() or int(length) > limit):
            raise ValueError("Invalid or oversized HTTP response")
        output = bytearray()
        while len(output) <= limit:
            if time.monotonic() - started > Limits.HTTP_TIMEOUT_SECONDS:
                raise ValueError("HTTP operation timed out")
            chunk = response.read(min(65536, limit + 1 - len(output)))
            if not chunk:
                break
            output.extend(chunk)
        if len(output) > limit or (length is not None and len(output) != int(length)):
            raise ValueError("Oversized or truncated HTTP response")
        return bytes(output)


def normalize_venv(venv: Path) -> None:
    """Remove only CPython's documented lib64 -> lib alias; reject other links."""
    alias = venv / "lib64"
    if alias.is_symlink():
        if (
            os.readlink(alias) != "lib"
            or not (venv / "lib").is_dir()
            or (venv / "lib").is_symlink()
        ):
            raise ValueError("Unexpected venv lib64 alias")
        alias.unlink()
    _validate_prepared_tree(venv)


def _validate_prepared_tree(venv: Path) -> None:
    count, total = 1, 0

    def walk(path, depth=0):
        nonlocal count, total
        if depth > Limits.TREE_DEPTH:
            raise ValueError("Prepared tree exceeds depth limit")
        with os.scandir(path) as entries:
            for entry in entries:
                count += 1
                info = entry.stat(follow_symlinks=False)
                if count > Limits.TREE_ENTRIES or info.st_mode & 0o7022:
                    raise ValueError("Unsafe or excessive prepared tree")
                if stat.S_ISDIR(info.st_mode):
                    walk(entry.path, depth + 1)
                elif stat.S_ISREG(info.st_mode) and info.st_nlink == 1:
                    total += info.st_size
                    if info.st_size > Limits.FILE_BYTES or total > Limits.TREE_BYTES:
                        raise ValueError("Prepared tree exceeds byte limit")
                else:
                    raise ValueError("Unexpected link or special file in prepared tree")

    walk(venv)


def prepare_dependencies(candidate: Path, *, runner=subprocess.run) -> None:
    _unprivileged()
    env = {
        "PATH": "/usr/bin:/bin",
        "LANG": "C.UTF-8",
        "HOME": "/tmp",
        "PIP_CONFIG_FILE": "/dev/null",
    }
    options = dict(
        check=True,
        env=env,
        cwd=str(candidate),
        stdin=subprocess.DEVNULL,
        timeout=Limits.DEPENDENCY_TIMEOUT_SECONDS,
    )
    venv = candidate / "venv"
    runner(["/usr/bin/python3", "-I", "-m", "venv", "--copies", str(venv)], **options)
    runner(
        [
            str(venv / "bin/python"),
            "-I",
            "-m",
            "pip",
            "--isolated",
            "install",
            "--no-cache-dir",
            "--disable-pip-version-check",
            "-r",
            str(candidate / "requirements.txt"),
        ],
        **options,
    )
    normalize_venv(venv)
    _validate_prepared_tree(candidate)


def run_stage(stage: str, workspace: Path, candidate: Path | None) -> None:
    _unprivileged()
    # Coordinator owns workspace and input files; only output/ and (in two stages)
    # candidate are child-writable. Never use a child-written manifest for extraction.
    output = workspace / "output"
    request = parse_object((workspace / "input.json").read_bytes(), Limits.CONFIG_BYTES)
    if stage == "metadata":
        channel = request.get("channel")
        base = f"https://api.github.com/repos/{REPOSITORY}/releases"
        if channel == "stable":
            data = download(base + "/latest", Limits.METADATA_BYTES)
        elif channel == "prerelease":
            pages = []
            budget = Limits.METADATA_BYTES
            for page in range(1, Limits.METADATA_PAGES + 1):
                raw = download(base + f"?per_page=100&page={page}", budget)
                budget -= len(raw)
                values = json.loads(raw)
                if not isinstance(values, list):
                    raise ValueError("Invalid release listing")
                pages.append(values)
                if len(values) < 100:
                    break
            else:
                raise ValueError("Release listing exceeds page limit")
            data = json.dumps(pages, allow_nan=False).encode()
            if len(data) > Limits.METADATA_BYTES:
                raise ValueError("Metadata exceeds limit")
        else:
            raise ValueError("Unsupported channel")
        (output / "metadata.json").write_bytes(data)
    elif stage == "download":
        release = ReleaseInfo(**request["release"])
        _check_release(release)
        (output / "archive.tar.gz").write_bytes(download(release.archive_url, Limits.ARCHIVE_BYTES))
        (output / "archive.sha256").write_bytes(
            download(release.checksum_url, Limits.CHECKSUM_BYTES)
        )
    elif stage == "extract" and candidate is not None:
        release = ReleaseInfo(**request["release"])
        extract_archive(workspace / "verified.tar.gz", candidate, release)
    elif stage == "dependencies" and candidate is not None:
        prepare_dependencies(candidate)
    elif stage == "migrate" and candidate is not None:
        subprocess.run(
            [
                "/usr/bin/python3",
                "-I",
                str(candidate / "installer/config_migrations.py"),
                "--migrate-copy",
                str(workspace / "config-input.json"),
                "--output",
                str(output / "config.json"),
            ],
            check=True,
            cwd="/",
            stdin=subprocess.DEVNULL,
            env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "HOME": "/tmp"},
            timeout=Limits.CHILD_TIMEOUT_SECONDS,
        )
    else:
        raise ValueError("Unsupported child operation")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "stage", choices=("metadata", "download", "extract", "dependencies", "migrate")
    )
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--candidate", type=Path)
    args = parser.parse_args()
    run_stage(args.stage, args.workspace, args.candidate)


if __name__ == "__main__":
    main()
