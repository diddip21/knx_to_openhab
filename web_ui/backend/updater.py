"""
Version management and update functionality for KNX to OpenHAB Generator.
Uses Git commits for versioning instead of version.json.
"""

import json
import os
import re
import subprocess
import threading
import time
from datetime import datetime
from typing import Any, Dict, Optional, Sequence, Tuple

import requests  # type: ignore[import]

_RELEASE_CACHE_TTL_SECONDS = 300

_SEMVER_PATTERN = re.compile(
    r"^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
    r"(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$"
)


def _parse_semver(tag: str) -> Optional[Tuple[int, int, int, Optional[Tuple[str, ...]]]]:
    match = _SEMVER_PATTERN.fullmatch(tag)
    if not match:
        return None

    prerelease = match.group(4)
    identifiers = tuple(prerelease.split(".")) if prerelease else None
    if identifiers and any(
        identifier.isdigit() and len(identifier) > 1 and identifier.startswith("0")
        for identifier in identifiers
    ):
        return None
    return int(match.group(1)), int(match.group(2)), int(match.group(3)), identifiers


def _compare_semver(left: str, right: str) -> Optional[int]:
    """Return -1/0/1 by SemVer precedence, or None if either tag is invalid."""
    left_version = _parse_semver(left)
    right_version = _parse_semver(right)
    if left_version is None or right_version is None:
        return None

    left_core = left_version[:3]
    right_core = right_version[:3]
    if left_core != right_core:
        return (left_core > right_core) - (left_core < right_core)

    left_pre = left_version[3]
    right_pre = right_version[3]
    if left_pre is None or right_pre is None:
        if left_pre is None and right_pre is None:
            return 0
        return 1 if left_pre is None else -1

    for left_id, right_id in zip(left_pre, right_pre):
        if left_id == right_id:
            continue
        left_numeric = left_id.isdigit()
        right_numeric = right_id.isdigit()
        if left_numeric and right_numeric:
            return (int(left_id) > int(right_id)) - (int(left_id) < int(right_id))
        if left_numeric != right_numeric:
            return -1 if left_numeric else 1
        return (left_id > right_id) - (left_id < right_id)
    return (len(left_pre) > len(right_pre)) - (len(left_pre) < len(right_pre))


class Updater:
    """Handles version checking and updates from GitHub using Git commits."""

    def __init__(self, base_path: Optional[str] = None):
        """
        Initialize the updater.

        Args:
            base_path: Base directory of the installation (defaults to current working directory)
        """
        self.base_path = base_path or os.path.dirname(
            os.path.dirname(os.path.dirname(__file__))
        )  # Project root
        self.repo_url = "https://github.com/diddip21/knx_to_openhab"
        self.branch = "stable releases"
        self._release_cache: Optional[Tuple[float, Dict[str, Any]]] = None
        self._release_cache_lock = threading.Lock()

    def _run_git_command(self, args: Sequence[str]) -> Tuple[bool, str]:
        """
        Run a git command and return the result.

        Args:
            args: List of git command arguments

        Returns:
            Tuple of (success, output)
        """
        try:
            result = subprocess.run(
                ["git"] + list(args),
                cwd=self.base_path,
                capture_output=True,
                text=True,
                timeout=10,
            )
            return result.returncode == 0, result.stdout.strip()
        except Exception as e:
            return False, str(e)

    def get_current_version(self) -> Dict[str, Any]:
        """
        Get the current version information from local git repository.

        Returns:
            Dictionary with version info (commit_hash, commit_date, branch, repository)
        """
        try:
            current_link = os.path.join(self.base_path, "current")
            if os.path.lexists(current_link):
                version_file = os.path.join(current_link, "version.json")
                try:
                    with open(version_file, encoding="utf-8") as source:
                        metadata = json.load(source)
                except (OSError, json.JSONDecodeError) as error:
                    return {
                        "commit_hash": "unknown",
                        "commit_short": "unknown",
                        "commit_date": "unknown",
                        "commit_message": "Invalid active release metadata",
                        "branch": self.branch,
                        "repository": self.repo_url,
                        "error": str(error),
                    }
                commit_hash = metadata.get("commit_hash") if isinstance(metadata, dict) else None
                release_tag = metadata.get("release_tag") if isinstance(metadata, dict) else None
                if not isinstance(commit_hash, str) or not re.fullmatch(
                    r"[0-9a-f]{40}", commit_hash
                ):
                    return {
                        "commit_hash": "unknown",
                        "commit_short": "unknown",
                        "commit_date": "unknown",
                        "commit_message": "Invalid active release metadata",
                        "branch": self.branch,
                        "repository": self.repo_url,
                        "error": "Active release commit hash is invalid",
                    }
                version = {
                    "commit_hash": commit_hash,
                    "commit_short": commit_hash[:7],
                    "commit_date": metadata.get("commit_date", "unknown"),
                    "commit_message": metadata.get("commit_message", "No message"),
                    "branch": release_tag if isinstance(release_tag, str) else self.branch,
                    "repository": self.repo_url,
                }
                if isinstance(release_tag, str):
                    version["release_tag"] = release_tag
                return version

            # Get current commit hash
            success, commit_hash = self._run_git_command(["rev-parse", "HEAD"])
            if not success:
                return {
                    "commit_hash": "unknown",
                    "commit_short": "unknown",
                    "commit_date": "unknown",
                    "commit_message": "Git repository not found",
                    "branch": self.branch,
                    "repository": self.repo_url,
                    "error": "Not a git repository or git not available",
                }

            # Get commit date
            success, commit_date = self._run_git_command(["show", "-s", "--format=%ci", "HEAD"])

            # Get commit message (first line)
            success, commit_message = self._run_git_command(["show", "-s", "--format=%s", "HEAD"])

            # Get current branch
            success, current_branch = self._run_git_command(["rev-parse", "--abbrev-ref", "HEAD"])
            tag_success, release_tag = self._run_git_command(
                ["describe", "--tags", "--exact-match", "HEAD"]
            )

            version = {
                "commit_hash": commit_hash,
                "commit_short": (commit_hash[:7] if commit_hash != "unknown" else "unknown"),
                "commit_date": commit_date if commit_date else "unknown",
                "commit_message": commit_message if commit_message else "No message",
                "branch": current_branch if current_branch else self.branch,
                "repository": self.repo_url,
            }
            if tag_success and release_tag:
                version["release_tag"] = release_tag
            return version
        except Exception as e:
            return {
                "commit_hash": "unknown",
                "commit_short": "unknown",
                "commit_date": "unknown",
                "commit_message": "Error",
                "branch": self.branch,
                "repository": self.repo_url,
                "error": str(e),
            }

    def check_github_version(self) -> Tuple[bool, Dict[str, Any]]:
        """
        Check GitHub for the latest published stable release.

        Returns:
            Tuple of (success, commit_info_dict or None)
        """
        with self._release_cache_lock:
            now = time.monotonic()
            if self._release_cache is not None:
                cached_at, cached_release = self._release_cache
                if now - cached_at < _RELEASE_CACHE_TTL_SECONDS:
                    return True, dict(cached_release)

            success, release = self._fetch_github_version()
            if success:
                self._release_cache = (time.monotonic(), dict(release))
            return success, release

    def _fetch_github_version(self) -> Tuple[bool, Dict[str, Any]]:
        """Resolve the latest stable GitHub release and its commit metadata."""
        try:
            # Extract owner and repo from URL
            # e.g., https://github.com/diddip21/knx_to_openhab -> diddip21/knx_to_openhab
            parts = self.repo_url.rstrip("/").split("/")
            owner = parts[-2]
            repo = parts[-1].replace(".git", "")

            release_url = f"https://api.github.com/repos/{owner}/{repo}/releases/latest"
            release_response = requests.get(release_url, timeout=10)

            if release_response.status_code != 200:
                return False, {
                    "error": f"GitHub Releases API returned status {release_response.status_code}"
                }

            release_data = release_response.json()
            release_tag = release_data.get("tag_name")
            if (
                not isinstance(release_tag, str)
                or not _SEMVER_PATTERN.fullmatch(release_tag)
                or "-" in release_tag.split("+", 1)[0]
                or release_data.get("draft") is not False
                or release_data.get("prerelease") is not False
            ):
                return False, {"error": "Latest stable release metadata is invalid"}

            commit_url = f"https://api.github.com/repos/{owner}/{repo}/commits/{release_tag}"
            commit_response = requests.get(commit_url, timeout=10)
            if commit_response.status_code != 200:
                return False, {
                    "error": f"GitHub release commit API returned status {commit_response.status_code}"
                }
            commit_data = commit_response.json()

            return True, {
                "release_tag": release_tag,
                "commit_hash": commit_data["sha"],
                "commit_short": commit_data["sha"][:7],
                "commit_date": commit_data["commit"]["committer"]["date"],
                "commit_message": commit_data["commit"]["message"].split("\n")[
                    0
                ],  # First line only
                "author": commit_data["commit"]["author"]["name"],
                "repository": self.repo_url,
                "branch": release_tag,
            }

        except requests.RequestException as e:
            return False, {"error": f"Network error: {str(e)}"}
        except Exception as e:
            return False, {"error": f"Unexpected error: {str(e)}"}

    def check_for_updates(self) -> Dict[str, Any]:
        """
        Check if updates are available by comparing local and remote commits.

        Returns:
            Dictionary with update status and information
        """
        current = self.get_current_version()
        success, remote = self.check_github_version()

        if not success:
            return {
                "update_available": False,
                "current_commit": current.get("commit_short", "unknown"),
                "current_date": current.get("commit_date", "unknown"),
                "error": remote.get("error", "Failed to check for updates"),
            }

        # Compare commit hashes
        current_commit = current.get("commit_hash", "")
        remote_commit = remote.get("commit_hash", "")

        update_available = current_commit != remote_commit and current_commit != "unknown"
        current_release_tag = current.get("release_tag")
        if isinstance(current_release_tag, str):
            release_order = _compare_semver(remote.get("release_tag", ""), current_release_tag)
            if release_order is not None and release_order < 0:
                update_available = False

        return {
            "update_available": update_available,
            "current_commit": current.get("commit_short", "unknown"),
            "current_commit_full": current_commit,
            "current_date": current.get("commit_date", "unknown"),
            "current_message": current.get("commit_message", ""),
            "latest_commit": remote.get("commit_short", "unknown"),
            "latest_commit_full": remote_commit,
            "latest_date": remote.get("commit_date", "unknown"),
            "latest_message": remote.get("commit_message", ""),
            "latest_author": remote.get("author", "unknown"),
            "latest_release_tag": remote.get("release_tag", "unknown"),
            "current_release_tag": current_release_tag,
            "repository": self.repo_url,
            "branch": remote.get("release_tag", self.branch),
        }

    def trigger_update(self) -> Tuple[bool, str]:
        """
        Trigger the update process by executing update.sh script.

        Returns:
            Tuple of (success, message)
        """
        try:
            release_ok, release = self.check_github_version()
            release_tag = release.get("release_tag")
            if not release_ok or not isinstance(release_tag, str):
                return False, release.get("error", "Could not resolve the latest stable release")

            current = self.get_current_version()
            current_release_tag = current.get("release_tag")
            if isinstance(current_release_tag, str):
                release_order = _compare_semver(release_tag, current_release_tag)
                if release_order is not None and release_order < 0:
                    return False, "The installed release is newer than the latest stable release"

            current_link = os.path.join(self.base_path, "current")
            if os.path.lexists(current_link):
                update_script = os.path.join(current_link, "update.sh")
                if not os.path.isfile(update_script):
                    return False, f"Active release updater not found at {update_script}"
            else:
                update_script = os.path.join(self.base_path, "update.sh")

            if not os.path.exists(update_script):
                return False, f"Update script not found at {update_script}"

            # Make script executable (optional, since we run with bash explicitly)
            try:
                os.chmod(update_script, 0o755)
            except OSError:
                # Ignore permission errors (e.g. if file is owned by root but we are knxohui)
                # We can still execute it via bash if we have read permissions
                pass

            # Prepare log file
            log_file = os.path.join(self.base_path, "update.log")

            # Prepare environment with overrides to avoid writing to system logs
            # and to ensure the update runs from the actual install path.
            env = os.environ.copy()
            env["LOG_FILE"] = os.devnull
            env["INSTALL_DIR"] = self.base_path
            env["KNXOH_INSTALL_DIR"] = self.base_path
            env["RELEASE_TAG"] = release_tag
            env["RELEASE_COMMIT_HASH"] = str(release.get("commit_hash", ""))
            env["RELEASE_COMMIT_DATE"] = str(release.get("commit_date", ""))
            env["RELEASE_COMMIT_MESSAGE"] = str(release.get("commit_message", ""))
            env["RELEASE_AUTHOR"] = str(release.get("author", "unknown"))
            repository_parts = self.repo_url.rstrip("/").split("/")
            env["KNXOH_GITHUB_REPOSITORY"] = (
                f"{repository_parts[-2]}/{repository_parts[-1].removesuffix('.git')}"
            )

            # Write header to log
            try:
                with open(log_file, "w") as f:
                    f.write(f"--- Update triggered at {datetime.now()} ---\n")
            except Exception:
                pass  # If we can't write, we can't write. Popen might fail too then.

            # Execute update script in background
            # The script will handle git pull, dependency updates, and service restart
            # We redirect output to the log file

            # We need to keep the file handle open just long enough to pass it to Popen
            # Popen will duplicate it for the child process
            try:
                log_fd = open(log_file, "a")
                subprocess.Popen(
                    ["/bin/bash", update_script],
                    cwd=self.base_path,
                    stdout=log_fd,
                    stderr=subprocess.STDOUT,
                    env=env,
                    start_new_session=True,
                )
                # We can close the fd in the parent process now
                # The child process has its own handle
                # context manager wouldn't work easily here with Popen specific needs
                log_fd.close()
            except Exception as e:
                # If opening log file fails, try running without logging to it (fallback)
                subprocess.Popen(
                    ["/bin/bash", update_script],
                    cwd=self.base_path,
                    start_new_session=True,
                    env=env,
                )

            return (
                True,
                "Update process started. The service will restart automatically.",
            )

        except Exception as e:
            return False, f"Failed to start update: {str(e)}"

    def get_update_log(self) -> str:
        """Get content of the update log file."""
        log_file = os.path.join(self.base_path, "update.log")
        if not os.path.exists(log_file):
            return "No update log found."
        try:
            with open(log_file, "r") as f:
                return f.read()
        except Exception as e:
            return f"Error reading log: {str(e)}"
