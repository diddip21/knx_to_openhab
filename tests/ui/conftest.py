"""Pytest fixtures for UI tests."""
import multiprocessing
import time
import pytest
import requests
from web_ui.backend import app as flask_app


@pytest.fixture(scope="session")
def base_url():
    """Base URL for the web UI."""
    return "http://127.0.0.1:8080"


@pytest.fixture(scope="session")
def flask_server(base_url):
    """Start Flask server in a separate process for UI tests."""
    # Get the Flask app from web_ui.backend.app
    app_instance = flask_app.app
    
    def run_server():
        """Run Flask server."""
        app_instance.run(host="127.0.0.1", port=8080, debug=False, use_reloader=False)
    
    # Start server in separate process
    server_process = multiprocessing.Process(target=run_server)
    server_process.start()
    
    # Wait for server to be ready
    max_retries = 30
    for i in range(max_retries):
        try:
            response = requests.get(f"{base_url}/api/status", timeout=1)
            if response.status_code == 200:
                break
        except requests.exceptions.RequestException:
            if i == max_retries - 1:
                server_process.terminate()
                server_process.join()
                raise RuntimeError(f"Flask server did not start within {max_retries} seconds")
            time.sleep(1)
    
    yield base_url
    
    # Cleanup: terminate server
    server_process.terminate()
    server_process.join(timeout=5)
    if server_process.is_alive():
        server_process.kill()
