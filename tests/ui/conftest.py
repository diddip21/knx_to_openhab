import os
import sys
import threading
import time

import pytest
import requests

# Add project root to sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../"))
sys.path.append(PROJECT_ROOT)

# Add backend to sys.path so we can import app
BACKEND_DIR = os.path.join(PROJECT_ROOT, "web_ui", "backend")
sys.path.append(BACKEND_DIR)

from web_ui.backend.app import app, cfg


def _safe_artifact_name(name: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in name)


def run_server():
    """Run the Flask app."""
    # Disable auth for testing
    if "auth" not in cfg:
        cfg["auth"] = {}
    cfg["auth"]["enabled"] = False

    # Disable reloader to avoid main thread issues
    app.run(host="127.0.0.1", port=8081, use_reloader=False)


@pytest.fixture(scope="session")
def base_url():
    return "http://127.0.0.1:8081"


@pytest.fixture(scope="session", autouse=True)
def server(base_url):
    """Start the Flask server in a separate thread."""
    # Use a different port than default 8080 to avoid conflicts

    # Start server thread
    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()

    # Wait for server to be ready
    max_retries = 20
    for _ in range(max_retries):
        try:
            response = requests.get(f"{base_url}/api/status")
            if response.status_code == 200:
                print("Server is ready!")
                break
        except requests.ConnectionError:
            pass
        time.sleep(0.5)
    else:
        pytest.fail("Server failed to start within timeout")

    yield

    # Thread will be killed when main process exits (daemon=True)


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    if report.when != "call" or report.passed:
        return

    page = item.funcargs.get("page")
    if not page:
        return

    os.makedirs("test-artifacts", exist_ok=True)
    safe_name = _safe_artifact_name(item.nodeid.replace("::", "-"))
    screenshot_path = os.path.join("test-artifacts", f"{safe_name}.png")
    try:
        page.screenshot(path=screenshot_path, full_page=True)
    except Exception:
        pass
