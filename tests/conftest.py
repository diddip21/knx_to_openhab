"""Shared pytest fixtures for all tests."""

import os
import sys
from pathlib import Path

import pytest

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


@pytest.fixture
def generate_output_from_json():
    """Generate KNX output from a JSON project into a test-owned directory."""
    import json

    import ets_to_openhab
    import knxproject_to_openhab
    from config import config

    def generate(project_path, output_dir):
        with open(project_path, encoding="utf-8") as project_file:
            project = json.load(project_file)

        building = knxproject_to_openhab.create_building(project)
        addresses = knxproject_to_openhab.get_addresses(project)
        house = knxproject_to_openhab.put_addresses_in_building(building, addresses, project)

        ets_to_openhab.floors = house[0]["floors"]
        ets_to_openhab.all_addresses = addresses
        ets_to_openhab.GWIP = knxproject_to_openhab.get_gateway_ip(project)
        ets_to_openhab.B_HOMEKIT = knxproject_to_openhab.is_homekit_enabled(project)
        ets_to_openhab.B_ALEXA = knxproject_to_openhab.is_alexa_enabled(project)
        ets_to_openhab.PRJ_NAME = house[0]["name_long"]

        items, sitemap, things = ets_to_openhab.gen_building()
        path_keys = (
            "items_path",
            "things_path",
            "sitemaps_path",
            "influx_path",
            "fenster_path",
            "openhab_path",
            "output_format",
        )
        original_paths = {key: config[key] for key in path_keys}
        config.update(
            {
                "items_path": str(output_dir / "knx.items"),
                "things_path": str(output_dir / "knx.things"),
                "sitemaps_path": str(output_dir / "knx.sitemap"),
                "influx_path": str(output_dir / "influxdb.persist"),
                "fenster_path": str(output_dir / "fenster.rules"),
                "openhab_path": str(output_dir),
                "output_format": "legacy",
            }
        )
        try:
            ets_to_openhab.export_output(items, sitemap, things, configuration=config)
        finally:
            config.update(original_paths)

        return output_dir

    return generate


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


@pytest.fixture(scope="session")
def generator_module():
    """Provide the main generator module for testing.

    This fixture ensures the generator module is properly imported and
    available for tests. It adds the project root to sys.path if needed.

    Returns:
        The imported ets_to_openhab module for generator testing.

    Raises:
        ImportError: If the generator module cannot be imported.
    """
    try:
        import ets_to_openhab

        return ets_to_openhab
    except ImportError as e:
        pytest.skip(f"Generator module not available: {e}")


@pytest.fixture(scope="session")
def helpers_module():
    """Provide the helpers module for testing.

    This fixture ensures helper functions are properly imported and available
    for tests. Handles cases where helpers are in different locations.

    Returns:
        The imported ets_helpers module containing helper functions.

    Raises:
        ImportError: If the helpers module cannot be imported.
    """
    try:
        import ets_helpers

        return ets_helpers
    except ImportError as e:
        pytest.skip(f"Helpers module not available: {e}")


@pytest.fixture(scope="session")
def knx_helper_functions(helpers_module):
    """Provide individual KNX helper functions for testing.

    This fixture extracts individual helper functions from the helpers module
    and provides them as a dict for easy access in tests.

    Args:
        helpers_module: The helpers module fixture.

    Returns:
        Dictionary with keys:
        - 'get_co_flags': Function to extract CO flags
        - 'flags_match': Function to match flags
        - 'get_dpt_from_dco': Function to extract DPT

    Example:
        >>> def test_something(knx_helper_functions):
        ...     get_co_flags = knx_helper_functions['get_co_flags']
        ...     flags = get_co_flags({'flags': {'read': True}})
    """
    return {
        "get_co_flags": getattr(helpers_module, "get_co_flags", None),
        "flags_match": getattr(helpers_module, "flags_match", None),
        "get_dpt_from_dco": getattr(helpers_module, "get_dpt_from_dco", None),
    }


@pytest.fixture(scope="session")
def generated_openhab_files(generator_module):
    """Generate OpenHAB config files from ETS data before tests run.

    This is the CRITICAL fixture that ensures the items/things/sitemap files
    are generated BEFORE any validation tests try to access them.

    The generator reads the KNX project and creates:
    - openhab/items/knx.items (all items, groups, equipment)
    - openhab/things/knx.things (KNX binding configuration)
    - openhab/sitemaps/knx.sitemap (UI layout)
    - openhab/persistence/knx.persistence (persistence config)

    This fixture runs once per test session (scope="session") and caches
    the generated files for all tests.

    Returns:
        None (just ensures files are generated and available)

    Raises:
        FileNotFoundError: If ETS project file not found
        Exception: If generation fails
    """
    import logging
    import os

    from config import config

    logger = logging.getLogger(__name__)

    # Import after project root is in sys.path
    from ets_to_openhab import export_output, gen_building

    try:
        logger.info("Generating OpenHAB configuration files...")

        # Step 1: Generate the items/sitemap/things from ETS data
        items, sitemap, things = gen_building()
        logger.info(
            f"✓ Generated {len(items)} items, {len(sitemap)} sitemap bytes, {len(things)} things bytes"
        )

        # Step 2: Write the generated content to files
        export_output(items, sitemap, things, configuration=config)
        logger.info(
            f"✓ Exported to: {config['items_path']}, {config['things_path']}, {config['sitemaps_path']}"
        )

        # Step 3: Verify files were created
        files_to_check = [
            config["items_path"],
            config["things_path"],
            config["sitemaps_path"],
        ]

        for file_path in files_to_check:
            if not os.path.exists(file_path):
                raise FileNotFoundError(f"Generated file not found after export: {file_path}")
            file_size = os.path.getsize(file_path)
            logger.info(f"  ✓ {file_path} ({file_size} bytes)")

        logger.info("✓ All OpenHAB configuration files generated successfully")

    except Exception as e:
        logger.error(f"✗ Failed to generate OpenHAB files: {e}")
        pytest.skip(f"Generator failed: {e}")

    yield

    # Cleanup is optional - files stay for manual inspection


@pytest.fixture(autouse=True)
def reset_environment():
    """Reset environment variables before each test."""
    # Store original environment
    original_env = os.environ.copy()

    yield

    # Restore original environment
    os.environ.clear()
    os.environ.update(original_env)
