"""
Version management and update functionality for KNX to OpenHAB Generator.
Uses Git commits for versioning instead of version.json.
"""

import json
import os
import re
import shlex
import subprocess
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, Sequence, Tuple

import requests  # type: ignore[import]

from knxoh_paths import get_paths
from update_request_lock import update_request_lock

_RELEASE_CACHE_TTL_SECONDS = 300
_UPDATE_WORKER_UNIT = Path("/etc/systemd/system/knxohui-update.service")
_UPDATE_WORKER_LAUNCHER = Path("/usr/local/libexec/knx_to_openhab/launch_update.sh")
_SERVICE_UPDATE_HELPER = "/usr/local/sbin/knxohui-service-update"

_SEMVER_PATTERN = re.compile(
    r"^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
    r"(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$"
)


def _start_update_worker() -> Tuple[bool, str]:
    try:
        result = subprocess.run(
            [
                "/usr/bin/sudo",
                "-n",
                _SERVICE_UPDATE_HELPER,
                "start-web-update",
            ],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as error:
        return False, str(error)

    if result.returncode != 0:
        detail = (result.stderr or "").strip()
        return False, detail or "Could not start the isolated updater service."
    return True, ""


def _read_update_request_identity(request_path: Path) -> Tuple[str, str]:
    with request_path.open(encoding="utf-8") as request_file:
        request = json.load(request_file)
    if not isinstance(request, dict):
        raise ValueError("Pending update request has an invalid format.")

    release_tag = request.get("release_tag")
    request_id = request.get("request_id")
    if not isinstance(release_tag, str) or not _SEMVER_PATTERN.fullmatch(release_tag):
        raise ValueError("Pending update request has an invalid release tag.")
    if not isinstance(request_id, str) or not re.fullmatch(r"[0-9a-f]{32}", request_id):
        raise ValueError("Pending update request has an invalid identifier.")
    return release_tag, request_id


def _write_update_log_header(log_path: Path, release_tag: str, request_id: str) -> None:
    with log_path.open("w", encoding="utf-8") as log_file:
        log_file.write(f"Update queued for {release_tag} (request_id={request_id}).\n")
        log_file.flush()
        os.fsync(log_file.fileno())


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

    def _update_worker_setup_error(self) -> Optional[str]:
        """Return setup guidance when the isolated systemd updater is not ready."""
        if not _UPDATE_WORKER_UNIT.is_file() or not _UPDATE_WORKER_LAUNCHER.is_file():
            return self._update_worker_setup_instruction()
        if not Path(_SERVICE_UPDATE_HELPER).is_file():
            return self._update_worker_setup_instruction()

        try:
            permission = subprocess.run(
                [
                    "/usr/bin/sudo",
                    "-n",
                    "-l",
                    _SERVICE_UPDATE_HELPER,
                    "start-web-update",
                ],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return self._update_worker_setup_instruction()

        if permission.returncode != 0:
            return self._update_worker_setup_instruction()
        return None

    def _update_worker_setup_instruction(self) -> str:
        setup_script = Path(self.base_path) / "current" / "installer" / "setup.sh"
        if not setup_script.is_file():
            setup_script = Path(self.base_path) / "installer" / "setup.sh"
        command = shlex.join(["sudo", "bash", str(setup_script)])
        return (
            "The isolated update worker is not installed or authorized. "
            f"Run `{command}` once from an administrator terminal, then retry the Web UI update."
        )

    def trigger_update(self) -> Tuple[bool, str]:
        """
        Queue the selected release for the independent systemd updater unit.

        Returns:
            Tuple of (success, message)
        """
        try:
            data_dir = get_paths(self.base_path).data_dir
            with update_request_lock(data_dir, blocking=False) as acquired:
                if not acquired:
                    return False, "An update is already in progress. Try again later."
                return self._trigger_update_locked(data_dir)
        except Exception as e:
            return False, f"Failed to start update: {str(e)}"

    def _trigger_update_locked(self, data_dir: Path) -> Tuple[bool, str]:
        try:
            request_path = data_dir / "update-request.json"
            running_path = data_dir / "update-request.running.json"
            pending_exists = os.path.lexists(request_path)
            running_exists = os.path.lexists(running_path)
            if pending_exists and running_exists:
                return (
                    False,
                    "Conflicting update requests: both pending and running request files are present.",
                )
            if running_exists:
                try:
                    os.replace(running_path, request_path)
                except OSError as error:
                    return False, f"Could not recover the interrupted update request: {error}"
                pending_exists = True

            if pending_exists:
                try:
                    release_tag, request_id = _read_update_request_identity(request_path)
                except (OSError, ValueError) as error:
                    return False, f"Could not read the pending update request: {error}"
                setup_error = self._update_worker_setup_error()
                if setup_error:
                    return False, setup_error
                try:
                    _write_update_log_header(
                        Path(self.base_path) / "update.log", release_tag, request_id
                    )
                except OSError as error:
                    return False, f"Could not prepare the update log: {error}"
                started, detail = _start_update_worker()
                if started:
                    return (
                        True,
                        f"Pending update request for {release_tag} (request_id={request_id}) "
                        "started. The service will restart automatically.",
                    )
                return False, f"An update request is already pending or running: {detail}"

            release_ok, release = self.check_github_version()
            latest_release_tag = release.get("release_tag")
            if not release_ok or not isinstance(latest_release_tag, str):
                return False, release.get("error", "Could not resolve the latest stable release")

            current = self.get_current_version()
            current_release_tag = current.get("release_tag")
            if isinstance(current_release_tag, str):
                release_order = _compare_semver(latest_release_tag, current_release_tag)
                if release_order is not None and release_order < 0:
                    return False, "The installed release is newer than the latest stable release"

            commit_hash = release.get("commit_hash")
            commit_date = release.get("commit_date")
            commit_message = release.get("commit_message", "")
            author = release.get("author") or "unknown"
            if not isinstance(commit_hash, str) or not re.fullmatch(r"[0-9a-f]{40}", commit_hash):
                return False, "Selected release metadata is invalid: commit hash."
            if not isinstance(commit_date, str) or not commit_date or len(commit_date) > 80:
                return False, "Selected release metadata is invalid: commit date."
            try:
                datetime.fromisoformat(commit_date.replace("Z", "+00:00"))
            except ValueError:
                return False, "Selected release metadata is invalid: commit date."
            if not isinstance(commit_message, str) or len(commit_message) > 500:
                return False, "Selected release metadata is invalid: commit message."
            if not isinstance(author, str) or not author or len(author) > 200:
                return False, "Selected release metadata is invalid: author."

            current_link = os.path.join(self.base_path, "current")
            if os.path.lexists(current_link):
                update_script = os.path.join(current_link, "update.sh")
                if not os.path.isfile(update_script):
                    return False, f"Active release updater not found at {update_script}"
            else:
                update_script = os.path.join(self.base_path, "update.sh")

            if not os.path.exists(update_script):
                return False, f"Update script not found at {update_script}"

            setup_error = self._update_worker_setup_error()
            if setup_error:
                return False, setup_error

            repository_parts = self.repo_url.rstrip("/").split("/")
            repository = f"{repository_parts[-2]}/{repository_parts[-1].removesuffix('.git')}"
            request_id = uuid.uuid4().hex
            request = {
                "schema_version": 1,
                "request_id": request_id,
                "release_tag": latest_release_tag,
                "commit_hash": commit_hash,
                "commit_date": commit_date,
                "commit_message": commit_message,
                "author": author,
                "repository": repository,
            }
            data_dir.mkdir(parents=True, exist_ok=True)
            log_file = Path(self.base_path) / "update.log"
            try:
                _write_update_log_header(log_file, latest_release_tag, request_id)
            except OSError as error:
                return False, f"Could not prepare the update log: {error}"

            temporary_path = os.path.join(data_dir, f".update-request-{request_id}.tmp")
            existing_request = False
            try:
                with open(temporary_path, "x", encoding="utf-8") as request_file:
                    json.dump(request, request_file, ensure_ascii=True)
                    request_file.write("\n")
                    request_file.flush()
                    os.fsync(request_file.fileno())
                os.chmod(temporary_path, 0o600)
                try:
                    os.link(temporary_path, request_path)
                except FileExistsError:
                    existing_request = True
            finally:
                try:
                    os.unlink(temporary_path)
                except FileNotFoundError:
                    pass

            if existing_request:
                try:
                    release_tag, request_id = _read_update_request_identity(request_path)
                    _write_update_log_header(log_file, release_tag, request_id)
                except OSError as error:
                    return (
                        False,
                        f"Could not prepare the update log for the pending request: {error}",
                    )
                except ValueError as error:
                    return False, f"Could not read the pending update request: {error}"

            started, detail = _start_update_worker()
            if not started:
                if existing_request:
                    return False, f"An update request is already pending or running: {detail}"
                return False, detail

            if existing_request:
                return (
                    True,
                    f"Pending update request for {release_tag} (request_id={request_id}) "
                    "started. The service will restart automatically.",
                )

            return (
                True,
                f"Update request for {latest_release_tag} (request_id={request_id}) started. "
                "The service will restart automatically.",
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
