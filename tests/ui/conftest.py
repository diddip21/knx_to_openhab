"""Pytest fixtures for UI tests."""
import subprocess
import time
import sys
import os
import pytest
import requests


@pytest.fixture(scope="session")
def base_url():
    """Base URL for the web UI."""
    return "http://127.0.0.1:8080"


@pytest.fixture(scope="session")
def flask_server(base_url):
    """Start Flask server as subprocess for UI tests."""
    # Start server using subprocess instead of multiprocessing
    # This is more reliable in CI environments
    env = os.environ.copy()
    env["FLASK_ENV"] = "testing"
    
    server_process = subprocess.Popen(
        [sys.executable, "-m", "web_ui.backend.app"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )
    
    # Wait for server to be ready
    max_retries = 30
    server_ready = False
    
    for i in range(max_retries):
        try:
            response = requests.get(f"{base_url}/api/status", timeout=2)
            if response.status_code in [200, 401]:  # 200 ok, 401 means auth but server is up
                server_ready = True
                break
        except requests.exceptions.RequestException:
            if server_process.poll() is not None:
                # Server crashed, get error output
                stdout, stderr = server_process.communicate(timeout=1)
                raise RuntimeError(
                    f"Flask server crashed during startup.\n"
                    f"Stdout: {stdout}\n"
                    f"Stderr: {stderr}"
                )
            time.sleep(1)
    
    if not server_ready:
        server_process.terminate()
        try:
            stdout, stderr = server_process.communicate(timeout=2)
        except subprocess.TimeoutExpired:
            server_process.kill()
            stdout, stderr = server_process.communicate()
        raise RuntimeError(
            f"Flask server did not start within {max_retries} seconds.\n"
            f"Stdout: {stdout}\n"
            f"Stderr: {stderr}"
        )
    
    yield base_url
    
    # Cleanup: terminate server
    server_process.terminate()
    try:
        server_process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        server_process.kill()
        server_process.wait()
