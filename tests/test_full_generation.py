import pytest
import shutil
import os
import json
import logging
from pathlib import Path
from unittest.mock import patch, MagicMock

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
PROJECT_FILES = list(TEST_FILES_DIR.glob("*.knxproj")) + list(TEST_FILES_DIR.glob("*.knxproj.json")) + \
                list(TEST_FILES_DIR.glob("*.knxprojarchive")) + list(TEST_FILES_DIR.glob("*.knxprojarchive.json"))
# Filter out json files if the corresponding knxproj exists to avoid double testing if desired
# But the user said "iterate through all files in tests/", suggesting coverage.
# The tool supports --readDump for JSONs.

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
    config.config['items_path'] = str(tmp_path / "openhab/items/knx.items")
    config.config['things_path'] = str(tmp_path / "openhab/things/knx.things")
    config.config['sitemaps_path'] = str(tmp_path / "openhab/sitemaps/knx.sitemap")
    config.config['influx_path'] = str(tmp_path / "openhab/persistence/influxdb.persist")
    config.config['fenster_path'] = str(tmp_path / "openhab/rules/fenster.rules")
    
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
    test_args.knxPW = None # Assume no password or hardcoded if needed
    test_args.readDump = project_file.suffix == '.json'
    
    # Patch argparse to return our args
    with patch('argparse.ArgumentParser.parse_args', return_value=test_args), \
         patch('sys.argv', ['knxproject_to_openhab.py']), \
         patch('tkinter.Tk', MagicMock()): # Mock GUI just in case
        
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
            if "Password required" in str(e) or "InvalidPasswordException" in type(e).__name__:
                pytest.skip(f"Skipping password protected project: {e}")
            pytest.fail(f"Execution failed with exception: {e}")

    # 1. Log Validation
    # check for ERROR or WARNING
    # We rely on caplog fixture
    errors = [r for r in caplog.records if r.levelname in ('ERROR', 'CRITICAL')]
    if errors:
        error_messages = "\n".join([r.message for r in errors])
        pytest.fail(f"Found errors in log:\n{error_messages}")
    
    # Warnings - maybe strict mode?
    warnings = [r for r in caplog.records if r.levelname == 'WARNING']
    if warnings:
        # For now just log them
        logger.warning(f"Found {len(warnings)} warnings.")

    # 2. File Existence Validation
    assert os.path.exists(config.config['items_path']), "Items file was not created"
    assert os.path.exists(config.config['things_path']), "Things file was not created"
    assert os.path.exists(config.config['sitemaps_path']), "Sitemap file was not created"
    
    assert os.path.getsize(config.config['items_path']) > 0, "Items file is empty"
    
    # 3. Semantic Validation
    items_content = open(config.config['items_path'], 'r', encoding='utf-8').read()
    things_content = open(config.config['things_path'], 'r', encoding='utf-8').read()
    
    #parsed_items = validation_logic.parse_items_file(items_content)
    #parsed_things = validation_logic.parse_things_file(things_content)
    
    # Reconstruct project structure from globals for validation
    # The `house` structure is roughly what `ets_to_openhab.floors` holds (list of floors)
    # We wrap it in a pseudo-building list as `validate_project_structure` expects
    #project_structure = [{'floors': ets_to_openhab.floors}]
    
    #structure_errors = validation_logic.validate_project_structure(parsed_items, project_structure)
    #if structure_errors:
    #    pytest.fail(f"Structure validation failed:\n" + "\n".join(structure_errors))
    logger.info(f"Successfully validated {project_file}")
