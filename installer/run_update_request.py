#!/usr/bin/env python3
"""Run one validated update request from the independent systemd updater unit."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

APP_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_ROOT))

from knxoh_paths import get_paths  # noqa: E402

_TAG = re.compile(
    r"^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$"
)
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_REQUEST_ID = re.compile(r"^[0-9a-f]{32}$")
_REPOSITORY = "diddip21/knx_to_openhab"
_REQUEST_NAME = "update-request.json"
_RUNNING_NAME = "update-request.running.json"


def _claim_request(request_path: Path) -> Path:
    running_path = request_path.with_name(_RUNNING_NAME)
    # A previous systemd worker may have been terminated before cleanup.
    running_path.unlink(missing_ok=True)
    try:
        os.replace(request_path, running_path)
    except FileNotFoundError as error:
        raise RuntimeError("No pending update request was found.") from error
    return running_path


def _validate_request(raw: Any) -> dict[str, str]:
    if not isinstance(raw, dict) or raw.get("schema_version") != 1:
        raise ValueError("Update request has an unsupported format.")

    request_id = raw.get("request_id")
    tag = raw.get("release_tag")
    commit_hash = raw.get("commit_hash")
    commit_date = raw.get("commit_date")
    commit_message = raw.get("commit_message", "")
    author = raw.get("author", "unknown")
    repository = raw.get("repository")
    if not isinstance(request_id, str) or not _REQUEST_ID.fullmatch(request_id):
        raise ValueError("Update request has an invalid request identifier.")
    if not isinstance(tag, str) or not _TAG.fullmatch(tag):
        raise ValueError("Update request contains an invalid stable release tag.")
    if not isinstance(commit_hash, str) or not _COMMIT.fullmatch(commit_hash):
        raise ValueError("Update request contains an invalid release commit hash.")
    if not isinstance(commit_date, str) or not commit_date or len(commit_date) > 80:
        raise ValueError("Update request contains an invalid release commit date.")
    try:
        datetime.fromisoformat(commit_date.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("Update request contains an invalid release commit date.") from error
    if not isinstance(commit_message, str) or len(commit_message) > 500:
        raise ValueError("Update request contains an invalid release commit message.")
    if any(ord(character) < 32 and character not in "\t" for character in commit_message):
        raise ValueError("Update request contains control characters in its commit message.")
    if not isinstance(author, str) or not author or len(author) > 200:
        raise ValueError("Update request contains an invalid release author.")
    if any(ord(character) < 32 and character not in "\t" for character in author):
        raise ValueError("Update request contains control characters in its release author.")
    if repository != _REPOSITORY:
        raise ValueError("Update request targets an unexpected repository.")

    return {
        "release_tag": tag,
        "commit_hash": commit_hash,
        "commit_date": commit_date,
        "commit_message": commit_message,
        "author": author,
        "repository": repository,
    }


def run_update_request() -> int:
    paths = get_paths(APP_ROOT)
    request_path = paths.data_dir / _REQUEST_NAME
    running_path: Path | None = None
    log_path = paths.install_dir / "update.log"

    try:
        running_path = _claim_request(request_path)
        raw_request = json.loads(running_path.read_text(encoding="utf-8"))
        release = _validate_request(raw_request)
        current_link = paths.install_dir / "current"
        if current_link.exists() or current_link.is_symlink():
            app_dir = current_link
        else:
            app_dir = paths.install_dir
        update_script = app_dir / "update.sh"
        if not update_script.is_file():
            raise RuntimeError(f"Update script not found: {update_script}")

        environment = os.environ.copy()
        environment.update(
            {
                "INSTALL_DIR": str(paths.install_dir),
                "KNXOH_INSTALL_DIR": str(paths.install_dir),
                "KNXOH_DATA_DIR": str(paths.data_dir),
                "KNXOH_CONFIG_DIR": str(paths.config_dir),
                "KNXOH_BACKUP_DIR": str(paths.backup_dir),
                "LOG_FILE": str(log_path),
                "RELEASE_TAG": release["release_tag"],
                "RELEASE_COMMIT_HASH": release["commit_hash"],
                "RELEASE_COMMIT_DATE": release["commit_date"],
                "RELEASE_COMMIT_MESSAGE": release["commit_message"],
                "RELEASE_AUTHOR": release["author"],
                "KNXOH_GITHUB_REPOSITORY": release["repository"],
            }
        )

        with log_path.open("a", encoding="utf-8") as log_file:
            log_file.write(
                f"Starting isolated updater for {release['release_tag']} "
                f"({release['commit_hash'][:7]}).\n"
            )
            log_file.flush()
            result = subprocess.run(
                ["/bin/bash", str(update_script)],
                cwd=paths.install_dir,
                env=environment,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                check=False,
            )
        return result.returncode
    except Exception as error:
        try:
            with log_path.open("a", encoding="utf-8") as log_file:
                log_file.write(f"Updater worker failed: {error}\n")
        except OSError:
            print(f"Updater worker failed: {error}", file=sys.stderr)
        return 1
    finally:
        if running_path is not None:
            running_path.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(run_update_request())
