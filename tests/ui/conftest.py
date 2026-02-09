"""Pytest fixtures for UI tests."""

import os
import subprocess
import sys
import time

import pytest
import requests
from playwright.sync_api import expect


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
    username = os.getenv("UI_AUTH_USER", "admin")
    password = os.getenv("UI_AUTH_PASSWORD", "logihome")
    return {
        **browser_context_args,
        "http_credentials": {"username": username, "password": password},
    }


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
