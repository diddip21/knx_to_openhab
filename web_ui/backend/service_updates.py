"""APT package versions and deliberately narrow, asynchronous service upgrades."""

import os
import subprocess
import threading
from typing import Any

PACKAGES = {"openhab": "openhab.service", "evcc": "evcc.service"}
HELPER = "/usr/local/sbin/knxohui-service-update"


def _command(args: list[str], timeout: int = 10) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
        env={**os.environ, "LC_ALL": "C"},
    )


def package_version(package: str) -> dict[str, Any]:
    """Compare installed package against the candidate in the local APT lists."""
    if package not in PACKAGES:
        raise ValueError("Unsupported service")
    result: dict[str, Any] = {
        "package": package,
        "installed": None,
        "candidate": None,
        "update_available": False,
        "supported": False,
        "message": "APT package is not installed on this host.",
    }
    try:
        installed = _command(["dpkg-query", "-W", "-f=${Version}", "--", package])
        if installed.returncode != 0 or not installed.stdout.strip():
            return result
        result["installed"] = installed.stdout.strip()
        policy = _command(["apt-cache", "policy", package])
        if policy.returncode != 0:
            result["message"] = "APT package information is unavailable."
            return result
        candidate = next(
            (
                line.split(":", 1)[1].strip()
                for line in policy.stdout.splitlines()
                if line.strip().startswith("Candidate:")
            ),
            None,
        )
        if not candidate or candidate == "(none)":
            result["message"] = "No APT candidate is available for this package."
            return result
        result["candidate"] = candidate
        result["supported"] = True
        newer = _command(["dpkg", "--compare-versions", candidate, "gt", result["installed"]])
        result["update_available"] = newer.returncode == 0
        result["message"] = "APT candidate from local package lists."
        return result
    except (OSError, subprocess.TimeoutExpired):
        result["message"] = "APT package information could not be read."
        return result


class ServiceUpdates:
    """One update or package-list refresh at a time in the single UI worker."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.task: dict[str, Any] = {"action": None, "state": "idle", "message": ""}

    def status(self) -> dict[str, Any]:
        with self.lock:
            return self.task.copy()

    def start(self, action: str, expected_version: str | None = None) -> tuple[bool, str]:
        if action not in (*PACKAGES, "refresh"):
            return False, "Unsupported action."
        if action in PACKAGES:
            version = package_version(action)
            if not version["supported"] or not version["update_available"]:
                return False, "No APT update is available for this package."
            if not expected_version or expected_version != version["candidate"]:
                return False, "APT candidate changed. Refresh the view and confirm again."
        if not os.path.isfile(HELPER):
            return False, "Update helper is not installed. Run sudo bash installer/setup.sh once."
        with self.lock:
            if self.task["state"] == "running":
                return False, "Another package operation is already running."
            self.task = {"action": action, "state": "running", "message": "Starting APT…"}
            threading.Thread(target=self._run, args=(action, expected_version), daemon=True).start()
        return True, "Package operation started."

    def _run(self, action: str, expected_version: str | None) -> None:
        try:
            proc = subprocess.run(
                ["sudo", "-n", HELPER, action],
                input=f"{expected_version}\n" if expected_version else None,
                capture_output=True,
                text=True,
                timeout=900,
                check=False,
            )
            state = "completed" if proc.returncode == 0 else "failed"
            output = (proc.stderr or proc.stdout).strip()
            message = (
                (
                    "Package lists refreshed."
                    if action == "refresh"
                    else f"{action} update finished."
                )
                if proc.returncode == 0
                else (output[-800:] or "APT operation failed.")
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            state, message = "failed", str(exc)
        with self.lock:
            self.task = {"action": action, "state": state, "message": message}
