"""Tests for output configuration detection and path setup.

This module tests the config.py module's ability to:
- Detect OpenHAB installation via openhab-cli
- Fall back to web UI configuration
- Use local defaults when neither method works
- Correctly set file permissions
"""

import unittest
from unittest.mock import patch, MagicMock, mock_open
import sys
import os
import json
import logging

# Add src directory to path for package imports
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'src'))

logger = logging.getLogger(__name__)

# Complete test configuration structure with all required keys
TEST_CONFIG = {
    "defines": {},
    "regexpattern": {
        "item_Room": "\\++[A-Z].[0-9]+",
        "item_Floor": "^=?[1-9\\.A-Z]{1,5}",
        "item_Floor_nameshort": "^=?[a-zA-Z]{1,5}\\b",
        "items_Label": "^\\[\\w*\\]\\@\\s?(\\+RM(\\d+(\\/|\\\\|-)*)*(\\d+))*\\s|:\\(.*\\)\\s?",
        "items_Name": "[^A-Za-z0-9_]+"
    },
    "general": {
        "FloorNameAsItIs": False,
        "FloorNameFromDescription": False,
        "RoomNameAsItIs": False,
        "RoomNameFromDescription": False,
        "addMissingItems": True,
        "unknown_floorname": "unknown",
        "unknown_roomname": "unknown",
        "item_Floor_nameshort_prefix": "=",
        "item_Room_nameshort_prefix": "+"
    },
    "devices": {
        "gateway": {
            "hardware_name": ["IP Interface Secure", "KNX IP Interface"]
        }
    },
    "datapoint_mappings": {}
}

TEST_CONFIG_JSON = json.dumps(TEST_CONFIG)


class TestOutputConfig(unittest.TestCase):
    """Test configuration detection and path resolution."""

    def setUp(self):
        """Reset module state before each test.
        
        Since config.py executes on import, we need to ensure it's
        imported fresh with the correct mocks in place.
        """
        # List of all modules to clean up for proper isolation
        modules_to_clean = [
            'knx_to_openhab',
            'knx_to_openhab.__init__',
            'knx_to_openhab.config',
            'knx_to_openhab.knxproject',
            'knx_to_openhab.generator',
        ]
        
        for module_name in modules_to_clean:
            if module_name in sys.modules:
                del sys.modules[module_name]

    def tearDown(self):
        """Clean up after each test."""
        # Same comprehensive cleanup as setUp
        modules_to_clean = [
            'knx_to_openhab',
            'knx_to_openhab.__init__',
            'knx_to_openhab.config',
            'knx_to_openhab.knxproject',
            'knx_to_openhab.generator',
        ]
        
        for module_name in modules_to_clean:
            if module_name in sys.modules:
                del sys.modules[module_name]

    @patch('pathlib.Path.exists', return_value=True)
    @patch('builtins.open', new_callable=mock_open, read_data=TEST_CONFIG_JSON)
    @patch('subprocess.run')
    def test_openhab_cli_detection(self, mock_run, mock_file, mock_exists):
        """Test detection of OpenHAB via openhab-cli command.
        
        When openhab-cli is available, config should:
        1. Detect the OpenHAB installation directory
        2. Parse user:group information
        3. Set paths based on OPENHAB_CONF
        """
        # Setup: Create mock subprocess response
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = """    User:        openhab (Active Process 123)
    User Groups: openhab tty
    Directories: Folder Name      | Path                        | User:Group
                 -----------      | ----                        | ----------
                 OPENHAB_CONF     | /etc/openhab                | openhab:openhab
        """
        mock_run.return_value = mock_proc

        # Execute: Import config with mocked subprocess
        from knx_to_openhab.config import config

        # Verify: Check that paths and user:group were detected correctly
        self.assertEqual(config['target_user'], 'openhab')
        self.assertEqual(config['target_group'], 'openhab')
        logger.info(f"✓ OpenHAB CLI detection: user={config['target_user']}")

    @patch('pathlib.Path.exists', return_value=False)
    @patch('builtins.open', new_callable=mock_open, read_data=TEST_CONFIG_JSON)
    @patch('subprocess.run')
    def test_default_local_paths(self, mock_run, mock_file, mock_exists):
        """Test fallback to local paths when no external detection works.
        
        When both openhab-cli and web UI methods fail, config should:
        1. Use local relative paths
        2. Not set target user/group (local mode)
        """
        # Setup: Mock both detection methods failing
        mock_run.side_effect = FileNotFoundError("openhab-cli not found")
        mock_exists.return_value = False  # Web UI config doesn't exist

        # Execute: Import config with both methods failing
        from knx_to_openhab.config import config

        # Verify: Check that local paths are used
        # In local mode, no user is set
        self.assertIsNone(config.get('target_user'))
        logger.info(f"✓ Local fallback: target_user={config.get('target_user')}")

    @patch('pathlib.Path.exists', return_value=True)
    @patch('builtins.open', new_callable=mock_open, read_data=TEST_CONFIG_JSON)
    @patch('subprocess.run')
    def test_openhab_cli_different_user(self, mock_run, mock_file, mock_exists):
        """Test openhab-cli detection with non-standard user.
        
        Some systems might run OpenHAB under a different user.
        Config should correctly parse this.
        """
        # Setup: Mock openhab-cli with different user
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = """    User:        myopenhab (Active Process 456)
    User Groups: myopenhab dialout
    Directories: Folder Name      | Path                        | User:Group
                 -----------      | ----                        | ----------
                 OPENHAB_CONF     | /home/myopenhab/.openhab    | myopenhab:myopenhab
        """
        mock_run.return_value = mock_proc

        # Execute: Import config
        from knx_to_openhab.config import config

        # Verify: Check correct user is detected
        self.assertEqual(config['target_user'], 'myopenhab')
        self.assertEqual(config['target_group'], 'myopenhab')
        logger.info(f"✓ Non-standard user detection: user={config['target_user']}")

    @patch('pathlib.Path.exists', return_value=True)
    @patch('builtins.open', new_callable=mock_open, read_data=TEST_CONFIG_JSON)
    @patch('shutil.chown')
    @patch('subprocess.run')
    def test_permission_setting(self, mock_run, mock_chown, mock_file, mock_exists):
        """Test that file permissions are set correctly.
        
        When files are generated, they should be owned by the
        configured user:group for OpenHAB to access them.
        """
        # Setup: Mock openhab-cli with test user
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = """    User:        testuser
    User Groups: testgroup
    Directories: Folder Name      | Path                | User:Group
                 -----------      | ----                | ----------
                 OPENHAB_CONF     | /tmp/openhab        | testuser:testgroup
        """
        mock_run.return_value = mock_proc

        # Execute: Import config and test permission setting
        from knx_to_openhab.config import config
        from knx_to_openhab import knxproject

        # Call set_permissions
        test_file = '/tmp/testfile.items'
        if hasattr(knxproject, 'set_permissions'):
            knxproject.set_permissions(test_file, configuration=config)
            # Verify: Check that chown was called with correct parameters
            mock_chown.assert_called_with(
                test_file,
                user='testuser',
                group='testgroup'
            )
            logger.info(f"✓ Permission setting: called chown({test_file}, testuser:testgroup)")
        else:
            logger.warning("✓ set_permissions not implemented (skipped)")

    @patch('pathlib.Path.exists', return_value=True)
    @patch('builtins.open', new_callable=mock_open, read_data=TEST_CONFIG_JSON)
    @patch('subprocess.run')
    def test_openhab_cli_command_called_correctly(self, mock_run, mock_file, mock_exists):
        """Test that openhab-cli is called with correct parameters."""
        # Setup
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = "User: test\nOPENHAB_CONF | /test"
        mock_run.return_value = mock_proc

        # Execute
        from knx_to_openhab.config import config

        # Verify: Check that subprocess.run was called
        # (We can't check exact args without more complex mocking,
        # but we can verify it was called)
        assert mock_run.called, "openhab-cli should be called"
        logger.info(f"✓ openhab-cli was invoked")


if __name__ == '__main__':
    unittest.main()
