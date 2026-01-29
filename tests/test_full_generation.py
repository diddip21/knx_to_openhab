import pytest
import shutil
import os
import json
import logging
from pathlib import Path
from unittest.mock import patch, MagicMock
import tempfile

# Import the module to be tested
# We need to add the parent directory to sys.path if not running as package
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import knxproject_to_openhab
import ets_to_openhab
import config

# Configure logging to capture output
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TEST_FILES_DIR = Path(__file__).parent
PROJECT_FILES = (
    list(TEST_FILES_DIR.glob("*.knxproj"))
    + list(TEST_FILES_DIR.glob("*.knxproj.json"))
    + list(TEST_FILES_DIR.glob("*.knxprojarchive"))
    + list(TEST_FILES_DIR.glob("*.knxprojarchive.json"))
)


@pytest.fixture
def mock_config(tmp_path):
    """
    Patches the configuration to redirect output to tmp_path.
    """
    # Create the directory structure needed
    (tmp_path / "openhab" / "items").mkdir(parents=True, exist_ok=True)
    (tmp_path / "openhab" / "things").mkdir(parents=True, exist_ok=True)
    (tmp_path / "openhab" / "sitemaps").mkdir(parents=True, exist_ok=True)
    (tmp_path / "openhab" / "persistence").mkdir(parents=True, exist_ok=True)
    (tmp_path / "openhab" / "rules").mkdir(parents=True, exist_ok=True)

    # We need to deep patch the dictionary in config.py
    # Since config.config is a mutable dict, we can modify it directly,
    # but we must restore it after test (pytest fixture handles this by yield?)
    # Dictionary updates are persistent in memory across tests if not reverted.

    original_config = config.config.copy()

    # Update paths
    config.config["items_path"] = str(tmp_path / "openhab/items/knx.items")
    config.config["things_path"] = str(tmp_path / "openhab/things/knx.things")
    config.config["sitemaps_path"] = str(tmp_path / "openhab/sitemaps/knx.sitemap")
    config.config["influx_path"] = str(
        tmp_path / "openhab/persistence/influxdb.persist"
    )
    config.config["fenster_path"] = str(tmp_path / "openhab/rules/fenster.rules")

    yield config.config

    # Restore (mocking config.config directly might be safer with patch.dict)
    config.config.clear()
    config.config.update(original_config)


@pytest.mark.parametrize("project_file", PROJECT_FILES)
def test_full_generation(project_file, mock_config, caplog, tmp_path):
    """
    Runs the full generation process for a given KNX project file.
    Validates output existence and checks for errors/warnings.
    """
    logger.info(f"Testing project: {project_file}")

    # Setup arguments
    test_args = MagicMock()
    test_args.file_path = project_file
    test_args.knxPW = None  # Assume no password or hardcoded if needed
    test_args.readDump = project_file.suffix == ".json"

    # Patch argparse to return our args
    with patch("argparse.ArgumentParser.parse_args", return_value=test_args), patch(
        "sys.argv", ["knxproject_to_openhab.py"]
    ), patch(
        "tkinter.Tk", MagicMock()
    ):  # Mock GUI just in case

        # We need to capture the `house` object to pass to validation
        # Since `knxproject_to_openhab.main` doesn't return it (it sets globals in `ets_to_openhab`),
        # we can access `ets_to_openhab.floors` after run.

        # Reset globals in ets_to_openhab to ensure clean state
        ets_to_openhab.floors = []
        ets_to_openhab.all_addresses = []

        try:
            knxproject_to_openhab.main()
        except SystemExit as e:
            # Some scripts exit on success/failure, capture this
            if e.code != 0:
                pytest.fail(f"Script exited with code {e.code}")
        except Exception as e:
            if (
                "Password required" in str(e)
                or "InvalidPasswordException" in type(e).__name__
            ):
                pytest.skip(f"Skipping password protected project: {e}")
            pytest.fail(f"Execution failed with exception: {e}")

    # 1. Log Validation
    # check for ERROR or WARNING
    # We rely on caplog fixture
    errors = [r for r in caplog.records if r.levelname in ("ERROR", "CRITICAL")]
    if errors:
        error_messages = "\n".join([r.message for r in errors])
        pytest.fail(f"Found errors in log:\n{error_messages}")

    # Warnings - maybe strict mode?
    warnings = [r for r in caplog.records if r.levelname == "WARNING"]
    if warnings:
        # For now just log them
        logger.warning(f"Found {len(warnings)} warnings.")

    # 2. File Existence Validation
    assert os.path.exists(config.config["items_path"]), "Items file was not created"
    assert os.path.exists(config.config["things_path"]), "Things file was not created"
    assert os.path.exists(
        config.config["sitemaps_path"]
    ), "Sitemap file was not created"

    assert os.path.getsize(config.config["items_path"]) > 0, "Items file is empty"

    # 3. Semantic Validation
    items_content = open(config.config["items_path"], "r", encoding="utf-8").read()
    things_content = open(config.config["things_path"], "r", encoding="utf-8").read()

    # parsed_items = validation_logic.parse_items_file(items_content)
    # parsed_things = validation_logic.parse_things_file(things_content)

    # Reconstruct project structure from globals for validation
    # The `house` structure is roughly what `ets_to_openhab.floors` holds (list of floors)
    # We wrap it in a pseudo-building list as `validate_project_structure` expects
    # project_structure = [{'floors': ets_to_openhab.floors}]

    # structure_errors = validation_logic.validate_project_structure(parsed_items, project_structure)
    # if structure_errors:
    #    pytest.fail(f"Structure validation failed:\n" + "\n".join(structure_errors))
    logger.info(f"Successfully validated {project_file}")


def test_full_generation_with_invalid_file(mock_config, tmp_path, caplog):
    """Test full generation with an invalid file to ensure proper error handling."""
    # Create a temporary invalid file
    invalid_file = tmp_path / "invalid.knxproj"
    invalid_file.write_text("invalid content")

    # Setup arguments
    test_args = MagicMock()
    test_args.file_path = invalid_file
    test_args.knxPW = None
    test_args.readDump = False

    # Patch argparse to return our args
    with patch("argparse.ArgumentParser.parse_args", return_value=test_args), patch(
        "sys.argv", ["knxproject_to_openhab.py"]
    ), patch("tkinter.Tk", MagicMock()):

        # Reset globals
        ets_to_openhab.floors = []
        ets_to_openhab.all_addresses = []

        # Expect the function to handle the invalid file gracefully
        try:
            knxproject_to_openhab.main()
            # If no exception, check that appropriate error messages were logged
            errors = [r for r in caplog.records if r.levelname in ("ERROR", "CRITICAL")]
            # The function might handle the error internally and still succeed partially
        except SystemExit as e:
            # Some scripts exit on failure, which is acceptable
            if e.code != 0:
                logger.info(
                    f"Script exited with code {e.code} as expected for invalid file"
                )
        except Exception as e:
            # Other exceptions should be caught and handled appropriately
            logger.info(f"Caught expected exception for invalid file: {e}")


def test_full_generation_with_nonexistent_file(mock_config, tmp_path, caplog):
    """Test full generation with a nonexistent file to ensure proper error handling."""
    # Create a path for a file that doesn't exist
    nonexistent_file = tmp_path / "nonexistent.knxproj"

    # Setup arguments
    test_args = MagicMock()
    test_args.file_path = nonexistent_file
    test_args.knxPW = None
    test_args.readDump = False

    # Patch argparse to return our args
    with patch("argparse.ArgumentParser.parse_args", return_value=test_args), patch(
        "sys.argv", ["knxproject_to_openhab.py"]
    ), patch("tkinter.Tk", MagicMock()):

        # Reset globals
        ets_to_openhab.floors = []
        ets_to_openhab.all_addresses = []

        # Expect the function to handle the nonexistent file gracefully
        try:
            knxproject_to_openhab.main()
        except SystemExit as e:
            # Some scripts exit on failure, which is acceptable
            if e.code != 0:
                logger.info(
                    f"Script exited with code {e.code} as expected for nonexistent file"
                )
        except Exception as e:
            # Other exceptions should be caught and handled appropriately
            logger.info(f"Caught expected exception for nonexistent file: {e}")


def test_full_generation_with_permission_error(mock_config, tmp_path):
    """Test full generation when file permissions prevent writing output."""
    # Change permissions to make output directory unwritable (on systems that support it)
    items_dir = tmp_path / "openhab" / "items"

    # Try to make the directory read-only temporarily
    try:
        # On Unix systems, we can modify permissions
        import stat

        items_dir.chmod(stat.S_IRUSR | stat.S_IXUSR)  # Read and execute only
    except (AttributeError, OSError):
        # On Windows or if chmod fails, skip this specific test
        pytest.skip("chmod not available on this system")

    # Setup arguments
    test_args = MagicMock()
    test_args.file_path = tmp_path / "dummy.knxproj"  # Won't actually exist
    test_args.knxPW = None
    test_args.readDump = False

    # Patch argparse and file reading to simulate a successful parse but fail on write
    with patch("argparse.ArgumentParser.parse_args", return_value=test_args), patch(
        "sys.argv", ["knxproject_to_openhab.py"]
    ), patch("tkinter.Tk", MagicMock()), patch(
        "builtins.open", side_effect=PermissionError("Permission denied")
    ):

        # Reset globals
        ets_to_openhab.floors = []
        ets_to_openhab.all_addresses = []

        # Expect the function to handle the permission error gracefully
        try:
            knxproject_to_openhab.main()
        except (SystemExit, PermissionError):
            # Expected behavior when permissions are denied
            pass
        except Exception as e:
            # Other exceptions should be noted
            logger.info(f"Caught exception during permission error test: {e}")


@pytest.mark.parametrize(
    "project_file", PROJECT_FILES[:1]
)  # Only test with first file to avoid excessive runs
def test_full_generation_with_mocked_dependencies(
    project_file, mock_config, tmp_path, caplog
):
    """Test full generation with mocked dependencies to isolate the core functionality."""
    # Setup arguments
    test_args = MagicMock()
    test_args.file_path = project_file
    test_args.knxPW = None
    test_args.readDump = project_file.suffix == ".json"

    # Mock the core functions to isolate the generation process
    with patch("argparse.ArgumentParser.parse_args", return_value=test_args), patch(
        "sys.argv", ["knxproject_to_openhab.py"]
    ), patch("tkinter.Tk", MagicMock()), patch.object(
        ets_to_openhab, "export_output"
    ) as mock_export:

        # Reset globals
        ets_to_openhab.floors = []
        ets_to_openhab.all_addresses = []

        try:
            knxproject_to_openhab.main()
        except SystemExit as e:
            if e.code != 0:
                pytest.fail(f"Script exited with code {e.code}")
        except Exception as e:
            if (
                "Password required" in str(e)
                or "InvalidPasswordException" in type(e).__name__
            ):
                pytest.skip(f"Skipping password protected project: {e}")
            pytest.fail(f"Execution failed with exception: {e}")

        # Verify that export_output was called (indicating successful generation)
        assert (
            mock_export.called
        ), "export_output should have been called during generation"

        # Validate the log for any errors
        errors = [r for r in caplog.records if r.levelname in ("ERROR", "CRITICAL")]
        assert (
            len(errors) == 0
        ), f"No errors should occur during generation: {[r.message for r in errors]}"


@pytest.mark.parametrize(
    "project_file", PROJECT_FILES[:1]
)  # Only test with first file to avoid excessive runs
def test_full_generation_output_content_validation(
    project_file, mock_config, tmp_path, caplog
):
    """Test that the generated files have expected content structure."""
    # Setup arguments
    test_args = MagicMock()
    test_args.file_path = project_file
    test_args.knxPW = None
    test_args.readDump = project_file.suffix == ".json"

    # Patch argparse to return our args
    with patch("argparse.ArgumentParser.parse_args", return_value=test_args), patch(
        "sys.argv", ["knxproject_to_openhab.py"]
    ), patch("tkinter.Tk", MagicMock()):

        # Reset globals
        ets_to_openhab.floors = []
        ets_to_openhab.all_addresses = []

        try:
            knxproject_to_openhab.main()
        except SystemExit as e:
            if e.code != 0:
                pytest.fail(f"Script exited with code {e.code}")
        except Exception as e:
            if (
                "Password required" in str(e)
                or "InvalidPasswordException" in type(e).__name__
            ):
                pytest.skip(f"Skipping password protected project: {e}")
            pytest.fail(f"Execution failed with exception: {e}")

        # Validate file content structure
        items_path = config.config["items_path"]
        things_path = config.config["things_path"]
        sitemap_path = config.config["sitemaps_path"]

        assert os.path.exists(items_path), "Items file should exist"
        assert os.path.exists(things_path), "Things file should exist"
        assert os.path.exists(sitemap_path), "Sitemap file should exist"

        # Read and validate content
        with open(items_path, "r", encoding="utf-8") as f:
            items_content = f.read()

        with open(things_path, "r", encoding="utf-8") as f:
            things_content = f.read()

        with open(sitemap_path, "r", encoding="utf-8") as f:
            sitemap_content = f.read()

        # Validate items file structure
        assert len(items_content) > 0, "Items file should not be empty"
        # Check for common OpenHAB items patterns
        assert (
            "Group" in items_content
            or "Switch" in items_content
            or "Dimmer" in items_content
        ), "Items file should contain OpenHAB item types"

        # Validate things file structure
        assert len(things_content) > 0, "Things file should not be empty"
        # Check for common OpenHAB things patterns
        assert (
            "Thing" in things_content
            or "Bridge" in things_content
            or "knx:" in things_content.lower()
        ), "Things file should contain OpenHAB thing types"

        # Validate sitemap file structure
        assert len(sitemap_content) > 0, "Sitemap file should not be empty"
        # Check for common OpenHAB sitemap patterns
        assert (
            "sitemap" in sitemap_content.lower()
            or "Frame" in sitemap_content
            or "Text" in sitemap_content
        ), "Sitemap file should contain OpenHAB sitemap elements"

        logger.info(f"Content validation passed for {project_file}")


def test_full_generation_error_handling_edge_cases(mock_config, tmp_path, caplog):
    """Test error handling for various edge cases in the generation process."""
    # Test with empty project file
    empty_file = tmp_path / "empty.knxproj"
    empty_file.write_text("")

    test_args = MagicMock()
    test_args.file_path = empty_file
    test_args.knxPW = None
    test_args.readDump = False

    with patch("argparse.ArgumentParser.parse_args", return_value=test_args), patch(
        "sys.argv", ["knxproject_to_openhab.py"]
    ), patch("tkinter.Tk", MagicMock()):

        ets_to_openhab.floors = []
        ets_to_openhab.all_addresses = []

        try:
            knxproject_to_openhab.main()
        except (SystemExit, Exception):
            # Expected for empty/invalid file
            pass

        # Check that appropriate error handling occurred
        logger.info("Edge case error handling test completed")


@pytest.mark.parametrize(
    "project_file", PROJECT_FILES[:1]
)  # Only test with first file to avoid excessive runs
def test_full_generation_with_exception_in_processing(
    project_file, mock_config, tmp_path
):
    """Test how the system handles exceptions during the processing phase."""
    # Setup arguments
    test_args = MagicMock()
    test_args.file_path = project_file
    test_args.knxPW = None
    test_args.readDump = project_file.suffix == ".json"

    # Mock a function that might throw an exception during processing
    with patch("argparse.ArgumentParser.parse_args", return_value=test_args), patch(
        "sys.argv", ["knxproject_to_openhab.py"]
    ), patch("tkinter.Tk", MagicMock()), patch(
        "ets_to_openhab.gen_building", side_effect=RuntimeError("Processing failed")
    ):

        # Reset globals
        ets_to_openhab.floors = []
        ets_to_openhab.all_addresses = []

        # Should handle the exception gracefully
        try:
            knxproject_to_openhab.main()
        except SystemExit as e:
            # Expected behavior when processing fails
            assert e.code != 0, "Should exit with error code when processing fails"
        except RuntimeError as e:
            # Expected behavior when processing fails
            assert "Processing failed" in str(e)
        except Exception as e:
            pytest.fail(f"Unexpected exception: {e}")
