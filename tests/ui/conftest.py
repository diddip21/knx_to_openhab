"""Pytest fixtures for UI tests."""

import base64
import json
import os
import socket
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import pytest
import requests
from playwright.sync_api import expect

_AUTH_PREVIEW_SESSION_FILE: Path | None = None


def pytest_collection_modifyitems(config, items):
    """Ensure all UI tests in this package are marked with @pytest.mark.ui."""
    for item in items:
        item.add_marker(pytest.mark.ui)


@pytest.fixture(autouse=True)
def configure_playwright_timeouts(page):
    """Set default Playwright timeouts for more reliable CI runs."""
    default_timeout = int(os.getenv("PLAYWRIGHT_TIMEOUT", "10000"))
    nav_timeout = int(os.getenv("PLAYWRIGHT_NAV_TIMEOUT", "30000"))
    expect_timeout = int(os.getenv("PLAYWRIGHT_EXPECT_TIMEOUT", "10000"))

    page.set_default_timeout(default_timeout)
    page.set_default_navigation_timeout(nav_timeout)
    expect.set_options(timeout=expect_timeout)


@pytest.fixture(scope="session")
def base_url():
    """Base URL for the web UI."""
    return os.getenv("UI_BASE_URL", "http://127.0.0.1:8085")


@pytest.fixture(scope="session")
def browser_context_args(browser_context_args):
    """Configure browser context for testing (basic auth + defaults)."""
    username = os.getenv("UI_AUTH_USER")
    password = os.getenv("UI_AUTH_PASSWORD")
    config = {**browser_context_args}
    if username and password:
        config["http_credentials"] = {"username": username, "password": password}
    return config


@pytest.fixture(scope="session")
def flask_server(base_url):
    """Start Flask server as subprocess for UI tests."""
    # Start server using subprocess
    env = os.environ.copy()
    env["FLASK_ENV"] = "testing"

    # Use -m to run as module, which triggers __main__.py
    server_process = subprocess.Popen(
        [sys.executable, "-m", "web_ui.backend"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,  # Merge stderr into stdout for easier debugging
        text=True,
        bufsize=1,  # Line buffered
    )

    # Wait for server to be ready
    max_retries = 30
    server_ready = False
    last_error = None

    for i in range(max_retries):
        # Check if process crashed
        if server_process.poll() is not None:
            # Server crashed, get error output
            output = server_process.stdout.read() if server_process.stdout else "No output"
            raise RuntimeError(
                "Flask server crashed during startup "
                f"(exit code: {server_process.returncode}).\n"
                f"Output:\n{output}"
            )

        try:
            response = requests.get(f"{base_url}/api/status", timeout=2)
            # 200 ok, 401 means auth but server is up
            if response.status_code in (200, 401):
                server_ready = True
                break
        except requests.exceptions.RequestException as e:
            last_error = str(e)
            time.sleep(1)

    if not server_ready:
        server_process.terminate()
        try:
            output = server_process.stdout.read() if server_process.stdout else "No output"
            server_process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            server_process.kill()
            server_process.wait()
        raise RuntimeError(
            f"Flask server did not start within {max_retries} seconds.\n"
            f"Last error: {last_error}\n"
            f"Server output:\n{output}"
        )

    print(f"Flask server started successfully on {base_url}")
    yield base_url

    # Cleanup: terminate server
    server_process.terminate()
    try:
        server_process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        server_process.kill()
        server_process.wait()


@pytest.fixture(scope="session")
def auth_preview_server(tmp_path_factory):
    """Run a separate authenticated instance for the login/dashboard screenshots."""
    from web_ui.backend.auth import hash_password

    project_root = Path(__file__).resolve().parents[2]
    temp_root = tmp_path_factory.mktemp("auth-preview")
    config_dir = temp_root / "config"
    data_dir = temp_root / "data"
    backup_dir = temp_root / "backups"
    config_dir.mkdir()
    global _AUTH_PREVIEW_SESSION_FILE
    _AUTH_PREVIEW_SESSION_FILE = data_dir / "sessions.sqlite3"
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]

    config = {
        "openhab_path": str(project_root / "openhab"),
        "jobs_dir": str(data_dir / "jobs"),
        "staging_dir": str(data_dir / "staging"),
        "generated_dir": str(data_dir / "generated"),
        "backups_dir": str(backup_dir),
        "sessions_file": str(data_dir / "sessions.sqlite3"),
        "bind_host": "127.0.0.1",
        "port": port,
        "trusted_proxy_hops": 0,
        "session_max_age_seconds": 43200,
        "auth": {"enabled": True, "user": "operator"},
        "retention": {"days": 14, "max_backups": 50, "max_backups_size_mb": 500},
        "general": {"auto_place_unknown": False},
    }
    (config_dir / "config.json").write_text(json.dumps(config), encoding="utf-8")
    password_hash = hash_password("test-only-preview-password")
    secret_lines = [
        "KNXOH_UI_PASSWORD_HASH_B64="
        + base64.b64encode(password_hash.encode("utf-8")).decode("ascii"),
        "KNXOH_SESSION_SECRET_B64=" + base64.b64encode(b"s" * 32).decode("ascii"),
    ]
    (config_dir / "secrets.env").write_text("\n".join(secret_lines) + "\n", encoding="utf-8")
    (config_dir / "generator.json").write_text(
        (project_root / "config.json").read_text(encoding="utf-8"), encoding="utf-8"
    )

    env = os.environ.copy()
    env.pop("FLASK_ENV", None)
    env.update(
        {
            "KNXOH_INSTALL_DIR": str(project_root),
            "KNXOH_CONFIG_DIR": str(config_dir),
            "KNXOH_DATA_DIR": str(data_dir),
            "KNXOH_BACKUP_DIR": str(backup_dir),
            "KNXOH_PATHS_FILE": str(temp_root / "missing-paths.env"),
        }
    )
    process = subprocess.Popen(
        [sys.executable, "-m", "web_ui.backend"],
        cwd=project_root,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    url = f"http://127.0.0.1:{port}"
    for _ in range(30):
        if process.poll() is not None:
            output = process.stdout.read() if process.stdout else "No output"
            raise RuntimeError(f"Authenticated preview server failed to start:\n{output}")
        try:
            response = requests.get(f"{url}/login", timeout=1)
            if response.status_code == 200:
                break
        except requests.exceptions.RequestException:
            time.sleep(1)
    else:
        process.terminate()
        output = process.stdout.read() if process.stdout else "No output"
        raise RuntimeError(f"Authenticated preview server did not start:\n{output}")

    yield url

    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


@pytest.fixture
def expire_auth_preview_session(auth_preview_server):
    """Expire the authenticated preview session while its dashboard stays open."""
    if _AUTH_PREVIEW_SESSION_FILE is None:
        raise RuntimeError("The authenticated preview session database was not initialized")

    def expire():
        with sqlite3.connect(_AUTH_PREVIEW_SESSION_FILE) as connection:
            connection.execute("DELETE FROM sessions")

    return expire
