"""Pytest fixtures for UI tests."""

import base64
import json
import os
import socket
import sqlite3
import subprocess
import sys
import threading
import time
from collections import deque
from pathlib import Path
from urllib.parse import urlsplit

import pytest
import requests
from playwright.sync_api import expect

_AUTH_PREVIEW_SESSION_FILE: Path | None = None


def _capture_process_output(process):
    """Drain a subprocess pipe continuously while retaining recent diagnostics."""
    output_lines = deque(maxlen=100)

    def drain():
        if process.stdout is not None:
            output_lines.extend(process.stdout)

    reader = threading.Thread(target=drain, name="pytest-server-output", daemon=True)
    reader.start()
    return output_lines, reader


def _recent_process_output(output_lines, reader):
    reader.join(timeout=1)
    return "".join(output_lines)


def pytest_collection_modifyitems(config, items):
    """Ensure all UI tests in this package are marked with @pytest.mark.ui."""
    ui_root = Path(__file__).resolve().parent
    for item in items:
        if Path(item.path).resolve().is_relative_to(ui_root):
            item.add_marker(pytest.mark.ui)


@pytest.fixture(autouse=True)
def configure_playwright_timeouts(request):
    """Set default Playwright timeouts for more reliable CI runs."""
    if "page" not in request.fixturenames:
        return
    page = request.getfixturevalue("page")
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
def ui_server_environment(tmp_path_factory):
    """Keep browser-server configuration and generated state outside the repo."""
    project_root = Path(__file__).resolve().parents[2]
    temp_root = tmp_path_factory.mktemp("ui-server")
    config_dir = temp_root / "config"
    data_dir = temp_root / "data"
    backup_dir = temp_root / "backups"
    config_dir.mkdir()
    data_dir.mkdir()
    backup_dir.mkdir()

    generator_config_file = data_dir / "generator.json"
    original_generator_config = (project_root / "config.json").read_bytes()
    generator_config_file.write_bytes(original_generator_config)
    configured_url = urlsplit(os.getenv("UI_BASE_URL", "http://127.0.0.1:8085"))
    (config_dir / "config.json").write_text(
        json.dumps(
            {
                "openhab_path": str(project_root / "openhab"),
                "bind_host": "127.0.0.1",
                "port": configured_url.port or 8085,
                "auth": {"enabled": False, "user": "admin"},
                "retention": {
                    "days": 14,
                    "max_backups": 50,
                    "max_backups_size_mb": 500,
                },
            }
        ),
        encoding="utf-8",
    )

    return {
        "environment": {
            "KNXOH_INSTALL_DIR": str(project_root),
            "KNXOH_CONFIG_DIR": str(config_dir),
            "KNXOH_DATA_DIR": str(data_dir),
            "KNXOH_BACKUP_DIR": str(backup_dir),
            "KNXOH_PATHS_FILE": str(temp_root / "missing-paths.env"),
        },
        "generator_config_file": generator_config_file,
        "original_generator_config": original_generator_config,
    }


@pytest.fixture(autouse=True)
def isolate_ui_generator_config(ui_server_environment):
    """Reset config mutations after each browser test to avoid cross-test leakage."""
    config_file = ui_server_environment["generator_config_file"]
    baseline = ui_server_environment["original_generator_config"]
    config_file.write_bytes(baseline)
    yield
    config_file.write_bytes(baseline)


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
def flask_server(base_url, ui_server_environment):
    """Start Flask server as subprocess for UI tests."""
    # Start server using subprocess
    env = os.environ.copy()
    env["FLASK_ENV"] = "testing"
    env.update(ui_server_environment["environment"])

    # Use -m to run as module, which triggers __main__.py
    server_process = subprocess.Popen(
        [sys.executable, "-m", "web_ui.backend"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,  # Line buffered
    )
    server_output, output_reader = _capture_process_output(server_process)

    # Wait for server to be ready
    max_retries = 30
    server_ready = False
    last_error = None

    for i in range(max_retries):
        # Check if process crashed
        if server_process.poll() is not None:
            # Server crashed, get error output
            output = _recent_process_output(server_output, output_reader) or "No output"
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
            server_process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            server_process.kill()
            server_process.wait()
        output = _recent_process_output(server_output, output_reader) or "No output"
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
    output_reader.join(timeout=1)


@pytest.fixture
def emulator_server(tmp_path):
    """Start a real Flask instance with every writable output isolated in tmp_path."""
    project_root = Path(__file__).resolve().parents[2]
    config_dir = tmp_path / "config"
    data_dir = tmp_path / "data"
    backup_dir = tmp_path / "backups"
    openhab_root = tmp_path / "openhab"
    for directory in (config_dir, data_dir, backup_dir, openhab_root):
        directory.mkdir(parents=True, exist_ok=True)

    managed_files = (
        "items/knx.items",
        "things/knx.things",
        "sitemaps/knx.sitemap",
        "persistence/influxdb.persist",
        "rules/fenster.rules",
        "yaml/knx.yaml",
        "unknown_report.json",
        "partial_report.json",
        "completeness_report.json",
    )
    for relative_path in managed_files:
        target = openhab_root / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("# emulator baseline\n", encoding="utf-8")

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]

    def posix_path(path):
        # deploy_policy stores managed paths in POSIX form on every platform.
        return str(path).replace("\\", "/")

    generator_config = json.loads((project_root / "config.json").read_text(encoding="utf-8"))
    generator_config["items_path"] = posix_path(openhab_root / "items" / "knx.items")
    generator_config["things_path"] = posix_path(openhab_root / "things" / "knx.things")
    generator_config["sitemaps_path"] = posix_path(openhab_root / "sitemaps" / "knx.sitemap")
    generator_config["influx_path"] = posix_path(openhab_root / "persistence" / "influxdb.persist")
    generator_config["fenster_path"] = posix_path(openhab_root / "rules" / "fenster.rules")
    generator_config["yaml_path"] = posix_path(openhab_root / "yaml" / "knx.yaml")
    generator_config["transform_dir_path"] = posix_path(openhab_root / "transform")
    (data_dir / "generator.json").write_text(
        json.dumps(generator_config, ensure_ascii=False), encoding="utf-8"
    )

    app_config = {
        "openhab_path": posix_path(openhab_root),
        "jobs_dir": posix_path(data_dir / "jobs"),
        "staging_dir": posix_path(data_dir / "staging"),
        "generated_dir": posix_path(data_dir / "generated"),
        "backups_dir": posix_path(backup_dir),
        "sessions_file": posix_path(data_dir / "sessions.sqlite3"),
        "bind_host": "127.0.0.1",
        "port": port,
        "trusted_proxy_hops": 0,
        "auth": {"enabled": False, "user": "admin"},
        "retention": {"days": 14, "max_backups": 50, "max_backups_size_mb": 500},
        "general": {"auto_place_unknown": False},
    }
    (config_dir / "config.json").write_text(
        json.dumps(app_config, ensure_ascii=False), encoding="utf-8"
    )

    env = os.environ.copy()
    env.pop("FLASK_ENV", None)
    env.update(
        {
            "KNXOH_INSTALL_DIR": str(project_root),
            "KNXOH_CONFIG_DIR": str(config_dir),
            "KNXOH_DATA_DIR": str(data_dir),
            "KNXOH_BACKUP_DIR": str(backup_dir),
            "KNXOH_PATHS_FILE": str(tmp_path / "missing-paths.env"),
        }
    )
    server_process = subprocess.Popen(
        [sys.executable, "-m", "web_ui.backend"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    server_output, output_reader = _capture_process_output(server_process)
    base_url = f"http://127.0.0.1:{port}"
    try:
        for _ in range(60):
            if server_process.poll() is not None:
                output = _recent_process_output(server_output, output_reader) or "No output"
                raise RuntimeError(
                    f"Emulator Flask server crashed (exit {server_process.returncode}).\n{output}"
                )
            try:
                response = requests.get(f"{base_url}/api/status", timeout=1)
                if response.status_code == 200:
                    break
            except requests.exceptions.RequestException:
                time.sleep(0.5)
        else:
            output = _recent_process_output(server_output, output_reader) or "No output"
            raise RuntimeError(f"Emulator Flask server did not start.\n{output}")

        yield {
            "base_url": base_url,
            "openhab_root": openhab_root,
            "data_dir": data_dir,
            "backup_dir": backup_dir,
            "generator_config": data_dir / "generator.json",
            "server_output": server_output,
        }
    finally:
        server_process.terminate()
        try:
            server_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server_process.kill()
            server_process.wait()
        output_reader.join(timeout=1)


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
        "auth": {"enabled": True, "user": "operator", "mode": "session"},
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
    server_output, output_reader = _capture_process_output(process)
    url = f"http://127.0.0.1:{port}"
    for _ in range(30):
        if process.poll() is not None:
            output = _recent_process_output(server_output, output_reader) or "No output"
            raise RuntimeError(f"Authenticated preview server failed to start:\n{output}")
        try:
            response = requests.get(f"{url}/login", timeout=1)
            if response.status_code == 200:
                break
        except requests.exceptions.RequestException:
            time.sleep(1)
    else:
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        output = _recent_process_output(server_output, output_reader) or "No output"
        raise RuntimeError(f"Authenticated preview server did not start:\n{output}")

    yield url

    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
    output_reader.join(timeout=1)


@pytest.fixture(scope="session")
def basic_auth_preview_server(tmp_path_factory):
    """Run an isolated Basic-authenticated app for the cookie-less UI screenshot."""
    from web_ui.backend.auth import hash_password

    project_root = Path(__file__).resolve().parents[2]
    temp_root = tmp_path_factory.mktemp("basic-auth-preview")
    config_dir = temp_root / "config"
    data_dir = temp_root / "data"
    backup_dir = temp_root / "backups"
    config_dir.mkdir()
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
        "auth": {
            "enabled": True,
            "user": "operator",
            "mode": "basic",
            "allowed_origins": ["https://relay.example.com"],
        },
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
    server_output, output_reader = _capture_process_output(process)
    url = f"http://127.0.0.1:{port}"
    for _ in range(30):
        if process.poll() is not None:
            output = _recent_process_output(server_output, output_reader) or "No output"
            raise RuntimeError(f"Basic-auth preview server failed to start:\n{output}")
        try:
            response = requests.get(url, auth=("operator", "test-only-preview-password"), timeout=1)
            if response.status_code == 200:
                break
        except requests.exceptions.RequestException:
            time.sleep(1)
    else:
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        output = _recent_process_output(server_output, output_reader) or "No output"
        raise RuntimeError(f"Basic-auth preview server did not start:\n{output}")

    yield url

    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
    output_reader.join(timeout=1)


@pytest.fixture
def expire_auth_preview_session(auth_preview_server):
    """Expire the authenticated preview session while its dashboard stays open."""
    if _AUTH_PREVIEW_SESSION_FILE is None:
        raise RuntimeError("The authenticated preview session database was not initialized")

    def expire():
        with sqlite3.connect(_AUTH_PREVIEW_SESSION_FILE) as connection:
            connection.execute("DELETE FROM sessions")

    return expire
