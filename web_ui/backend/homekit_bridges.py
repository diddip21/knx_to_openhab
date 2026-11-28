"""Configure additional HomeKit bridges through the local openHAB REST service."""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from homekit_config import bridge_count
from knxoh_paths import get_paths

SERVICE_PATH = "/services/org.openhab.homekit"
MAX_RESPONSE_BYTES = 128 * 1024


class HomekitBridgeError(ValueError):
    """A safe, secret-free error suitable for the local API and CLI."""

    def __init__(self, message: str, code: str = "unavailable", status: int = 502):
        super().__init__(message)
        self.code = code
        self.status = status


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class HomekitBridgeClient:
    def __init__(self, base_url: str, token_file: Path, openhab_root: Path | None = None):
        try:
            parsed = urlsplit(base_url)
        except ValueError:
            raise HomekitBridgeError("Invalid local openHAB REST URL.", "connection", 503) from None
        if (
            parsed.scheme not in {"http", "https"}
            or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/", "/rest", "/rest/"}
            or parsed.query
            or parsed.fragment
        ):
            raise HomekitBridgeError(
                "openHAB REST URL must be a local loopback HTTP(S) address.", "connection", 503
            )
        try:
            if parsed.port is not None and not 1 <= parsed.port <= 65535:
                raise ValueError
        except ValueError:
            raise HomekitBridgeError("Invalid openHAB REST port.", "connection", 503) from None
        self.base_url = f"{parsed.scheme}://{parsed.netloc}/rest"
        self.token_file = token_file
        self.openhab_root = openhab_root
        self.opener = build_opener(ProxyHandler({}), _NoRedirect())

    def _request(self, path: str, payload: dict | None = None):
        headers = {"Accept": "application/json"}
        try:
            token = self.token_file.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            token = ""
        except (OSError, UnicodeError):
            raise HomekitBridgeError(
                "Cannot read the openHAB API token file.", "credentials", 503
            ) from None
        if token:
            if any(ch.isspace() for ch in token) or ":" in token:
                raise HomekitBridgeError("Invalid openHAB API token file.", "credentials", 503)
            credentials = base64.b64encode(f"{token}:".encode()).decode("ascii")
            headers["Authorization"] = f"Basic {credentials}"
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        if data is not None:
            headers["Content-Type"] = "application/json"
        request = Request(
            self.base_url + path,
            data=data,
            headers=headers,
            method="GET" if data is None else "PUT",
        )
        try:
            with self.opener.open(request, timeout=5) as response:
                # PUT returns the OLD configuration (including its PIN). Do not
                # read, log, return or persist it; verify with a fresh GET instead.
                if data is not None or response.status == 204:
                    return {}
                raw = response.read(MAX_RESPONSE_BYTES + 1)
        except HTTPError as error:
            status = error.code
            error.close()
            if status in (401, 403):
                raise HomekitBridgeError(
                    "openHAB requires an administrator API token. See HomeKit bridge setup.",
                    "credentials",
                    503,
                ) from None
            if status == 404:
                raise HomekitBridgeError(
                    "Install the HomeKit system integration in openHAB first.", "addon_missing", 409
                ) from None
            raise HomekitBridgeError(
                "openHAB rejected the HomeKit configuration request."
            ) from None
        except (OSError, URLError, ValueError):
            raise HomekitBridgeError("Cannot reach the local openHAB REST API.") from None
        try:
            if len(raw) > MAX_RESPONSE_BYTES:
                raise ValueError
            result = json.loads(raw)
            if not isinstance(result, dict):
                raise ValueError
            return result
        except (ValueError, UnicodeError):
            raise HomekitBridgeError(
                "Invalid HomeKit configuration response from openHAB."
            ) from None

    def _configuration(self):
        service = self._request(SERVICE_PATH)  # A PID can exist even if the add-on is absent.
        if service.get("id") != "org.openhab.homekit":
            raise HomekitBridgeError(
                "Install the HomeKit system integration in openHAB first.", "addon_missing", 409
            )
        configuration = self._request(SERVICE_PATH + "/config")
        count = configuration.get("instances", 1)
        port = configuration.get("port", 9123)

        # ConfigAdmin may return an integral setting as a string.
        def integer(value):
            if type(value) is int:
                return value
            if isinstance(value, str) and re.fullmatch(r"[1-9][0-9]*", value):
                return int(value)
            raise HomekitBridgeError("Invalid HomeKit bridge count or port in openHAB.")

        count, port = integer(count), integer(port)
        if count < 1 or port < 1 or port + count - 1 > 65535:
            raise HomekitBridgeError("Invalid HomeKit bridge count or port in openHAB.")
        return count, port

    def status(self):
        count, port = self._configuration()
        return {
            "configured_count": count,
            "first_port": port,
            "last_port": port + count - 1,
            "runtime_status": "not_checked",
        }

    def _assert_not_file_managed(self):
        if self.openhab_root is None:
            return
        services = self.openhab_root / "services"
        try:
            if not services.exists():
                return
            if services.is_symlink() or not services.is_dir():
                raise OSError
            for path in services.glob("*.cfg"):
                if path.is_symlink() or not path.is_file() or path.stat().st_size > 1024 * 1024:
                    raise OSError
                text = path.read_text(encoding="utf-8-sig")
                exclusive = re.search(r"(?m)^\s*pid:\s*org\.openhab\.homekit\s*$", text)
                explicit = re.search(r"(?m)^\s*org\.openhab\.homekit\s*:\s*instances\s*[=:]", text)
                implicit = path.name in {"homekit.cfg", "org.openhab.homekit.cfg"} and re.search(
                    r"(?m)^\s*instances\s*[=:]", text
                )
                if exclusive or explicit or implicit:
                    raise HomekitBridgeError(
                        "HomeKit instances are file-managed. Update that setting in services/*.cfg first.",
                        "file_managed",
                        409,
                    )
        except (OSError, UnicodeError):
            raise HomekitBridgeError(
                "Cannot safely inspect openHAB service configuration files.", "file_managed", 409
            ) from None

    def ensure_count(self, requested: int):
        requested = bridge_count({"homekit_bridge_count": requested})
        before, port = self._configuration()
        if port + requested - 1 > 65535:
            raise HomekitBridgeError(
                "Requested bridges exceed the available TCP port range.", "invalid_count", 400
            )
        changed = requested > before
        if changed:
            self._assert_not_file_managed()
            # A partial update is merged by openHAB ConfigurationService.update(..., false).
            # Never send other settings or automatically decrease an observed count.
            self._request(SERVICE_PATH + "/config", {"instances": requested})
        after, port = self._configuration()
        if after < max(requested, before):
            raise HomekitBridgeError(
                "openHAB did not retain the requested bridge count. Check file-managed settings.",
                "not_verified",
                409,
            )
        return {
            "requested_count": requested,
            "previous_count": before,
            "configured_count": after,
            "changed": changed,
            "first_port": port,
            "last_port": port + after - 1,
            "runtime_status": "not_checked",
        }


def configured_client(fallback_root=None):
    # Use the same effective root as generation/deploy (openhab-cli detection
    # can override the backend's repository-local development fallback).
    from config import config as generator_config

    openhab_root = generator_config.get("openhab_path") or fallback_root
    return HomekitBridgeClient(
        os.environ.get("KNXOH_OPENHAB_REST_URL", "http://127.0.0.1:8080"),
        get_paths().config_dir / "openhab_api_token",
        Path(openhab_root) if openhab_root else None,
    )


def main():
    parser = argparse.ArgumentParser(description="Inspect or add local openHAB HomeKit bridges")
    parser.add_argument(
        "--count", type=int, help="Ensure at least this many bridges; never remove bridges"
    )
    args = parser.parse_args()
    try:
        from .storage import load_config

        client = configured_client(load_config()["openhab_path"])
        result = client.status() if args.count is None else client.ensure_count(args.count)
    except (HomekitBridgeError, ValueError) as error:
        parser.exit(1, f"{error}\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
