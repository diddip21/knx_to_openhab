"""Shared pytest fixtures for all tests."""

import pytest
import sys
import os
from pathlib import Path

# Add project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


@pytest.fixture(scope="session")
def project_root_dir():
    """Return the project root directory."""
    return project_root


@pytest.fixture(scope="session")
def config_file(project_root_dir):
    """Return path to config.json file."""
    config_path = project_root_dir / "config.json"
    if not config_path.exists():
        pytest.skip(f"Config file not found: {config_path}")
    return config_path


@pytest.fixture(scope="session")
def test_data_dir():
    """Return the test data directory."""
    data_dir = Path(__file__).parent / "fixtures"
    if not data_dir.exists():
        data_dir.mkdir(parents=True)
    return data_dir


@pytest.fixture
def temp_output_dir(tmp_path):
    """Create a temporary directory for test outputs."""
    output_dir = tmp_path / "output"
    output_dir.mkdir(exist_ok=True)
    return output_dir


@pytest.fixture(scope="session")
def skip_if_no_web_server():
    """Skip tests if web server is not running."""
    import socket
    
    def check_server(host="localhost", port=8085, timeout=1):
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            result = sock.connect_ex((host, port))
            sock.close()
            return result == 0
        except Exception:
            return False
    
    if not check_server():
        pytest.skip("Web server not running on localhost:8085")


@pytest.fixture(autouse=True)
def reset_environment():
    """Reset environment variables before each test."""
    # Store original environment
    original_env = os.environ.copy()
    
    yield
    
    # Restore original environment
    os.environ.clear()
    os.environ.update(original_env)
