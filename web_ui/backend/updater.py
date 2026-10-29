"""Unprivileged release-update facade; compatibility commit fields stay honest."""

import json
import subprocess
import threading
from pathlib import Path
from typing import Any, Dict, Optional, Sequence, Tuple

from installer.update_core import secure_fs as fs
from installer.update_core.artifacts import REPOSITORY, _precedence, select_release
from installer.update_core.protocol import Limits, Paths
from installer.update_prepare import download
from installer.update_submit import submit_update, validate_channel
from knxoh_paths import get_paths


class Updater:
    """The web process submits data, never starts a root Python/application script."""

    def __init__(self, base_path: Optional[str] = None):
        self.base_path = base_path or str(Path(__file__).resolve().parents[2])
        self.repo_url = f"https://github.com/{REPOSITORY}"
        self.branch = "main"  # Legacy API compatibility, NOT release selection.
        self._submission_state = threading.local()

    @property
    def last_update_status(self):
        return getattr(self._submission_state, "status", "failed")

    @last_update_status.setter
    def last_update_status(self, value):
        self._submission_state.status = value

    def _paths(self) -> Paths:
        paths = get_paths(self.base_path)
        return Paths(
            paths.install_dir / "releases",
            paths.install_dir / "current",
            paths.config_dir,
            paths.data_dir,
            paths.backup_dir,
        )

    def _run_git_command(self, args: Sequence[str]) -> Tuple[bool, str]:
        """Read-only development version fallback; never used to check/update releases."""
        try:
            result = subprocess.run(
                ["git", *args], cwd=self.base_path, capture_output=True, text=True, timeout=10
            )
            return result.returncode == 0, result.stdout.strip()
        except (OSError, subprocess.SubprocessError):
            return False, ""

    def get_current_version(self) -> Dict[str, Any]:
        info = {
            "commit_hash": "unknown",
            "commit_short": "unknown",
            "commit_date": "unknown",
            "commit_message": "Release artifact (commit metadata unavailable)",
            "branch": self.branch,
            "repository": self.repo_url,
            "version": "unknown",
        }
        try:
            with (Path(self.base_path) / "VERSION").open(encoding="ascii") as stream:
                version = stream.read(257).strip()
            _precedence(version)
            info["version"] = version
            return info
        except (OSError, ValueError, UnicodeError):
            pass
        # Preserve local Git version information for flat development checkouts.
        success, commit = self._run_git_command(["rev-parse", "HEAD"])
        if success:
            info["commit_hash"], info["commit_short"] = commit, commit[:7]
            for key, args in (
                ("commit_date", ["show", "-s", "--format=%ci", "HEAD"]),
                ("commit_message", ["show", "-s", "--format=%s", "HEAD"]),
                ("branch", ["rev-parse", "--abbrev-ref", "HEAD"]),
            ):
                ok, value = self._run_git_command(args)
                if ok and value:
                    info[key] = value
        return info

    def _metadata(self, channel):
        base = f"https://api.github.com/repos/{REPOSITORY}/releases"
        if channel == "stable":
            return json.loads(download(base + "/latest", Limits.METADATA_BYTES))
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
                return pages
        raise ValueError("Release listing exceeds page limit")

    def check_github_version(self, channel: str = "stable") -> Tuple[bool, Dict[str, Any]]:
        """Compatibility method, now backed by validated release assets, not commits."""
        try:
            validate_channel(channel)
            # Lowest valid SemVer lets this legacy method report the channel head.
            selected = select_release(self._metadata(channel), channel, "0.0.0-0")
            if selected is None:
                return False, {"error": "No compatible release found"}
            return True, {
                "version": selected.version,
                "commit_hash": "unknown",
                "commit_short": "unknown",
                "commit_date": "unknown",
                "commit_message": selected.tag,
                "author": "unknown",
                "repository": self.repo_url,
                "branch": self.branch,
            }
        except (OSError, ValueError, UnicodeError):
            return False, {"error": "Unable to read valid release metadata/assets from GitHub"}

    def check_for_updates(self, channel: str = "stable") -> Dict[str, Any]:
        current = self.get_current_version()
        result = {
            "update_available": False,
            "current_commit": current["commit_short"],
            "current_commit_full": current["commit_hash"],
            "current_date": current["commit_date"],
            "current_message": current["commit_message"],
            "latest_commit": "unknown",
            "latest_commit_full": "unknown",
            "latest_date": "unknown",
            "latest_message": "",
            "latest_author": "unknown",
            "repository": self.repo_url,
            "branch": self.branch,
            "current_version": current["version"],
            "latest_version": "unknown",
        }
        try:
            validate_channel(channel)
            _precedence(current["version"])
            metadata = self._metadata(channel)
            selected = select_release(metadata, channel, current["version"])
            # Validate assets even for equal/older channel head; malformed metadata
            # is an error, not a misleading successful "up to date" result.
            head = select_release(metadata, channel, "0.0.0-0")
            if head:
                result["latest_version"] = head.version
                result["latest_message"] = head.tag
            result["update_available"] = selected is not None
        except (OSError, ValueError, UnicodeError):
            result["error"] = (
                "Unable to check compatible release: unknown local VERSION or invalid/unavailable release metadata/assets"
            )
        return result

    def trigger_update(self, channel: str = "stable") -> Tuple[bool, str]:
        try:
            validate_channel(channel)
        except ValueError as error:
            self.last_update_status = "failed"
            return False, str(error)
        result = submit_update(self._paths(), channel)
        self.last_update_status = result.status
        if result.status == "submitted":
            return (
                True,
                "Update request accepted by the coordinator; completion is asynchronous. Check the update log.",
            )
        return False, result.error or "Release update could not be submitted"

    def get_update_log(self) -> str:
        """Only the bounded, root-owned public projection; never release logs."""
        try:
            raw = fs.read_regular(self._paths().config_dir / ".updater-log.txt", 4096)
            text = raw.decode("utf-8")
            if any(ord(c) < 32 and c != "\n" or ord(c) == 127 for c in text):
                raise ValueError("Invalid public log")
            return text
        except FileNotFoundError:
            return "No update log found."
        except (OSError, ValueError, UnicodeError, NotImplementedError):
            return "Error reading log: protected update log is unavailable or unsafe."
