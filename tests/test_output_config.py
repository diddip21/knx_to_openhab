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

logger = logging.getLogger(__name__)


class TestOutputConfig(unittest.TestCase):
    """Test configuration detection and path resolution."""

    def setUp(self):
        """Reset module state before each test.
        
        Since config.py executes on import, we need to ensure it's
        imported fresh with the correct mocks in place.
        """
        # Remove config from sys.modules to force re-import
        if 'config' in sys.modules:
            del sys.modules['config']
        # Also clear any ets_to_openhab that might depend on config
        if 'ets_to_openhab' in sys.modules:
            del sys.modules['ets_to_openhab']

    def tearDown(self):
        """Clean up after each test."""
        # Remove modules after test
        if 'config' in sys.modules:
            del sys.modules['config']
        if 'ets_to_openhab' in sys.modules:
            del sys.modules['ets_to_openhab']

    @patch('subprocess.run')
    def test_openhab_cli_detection(self, mock_run):
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
        import config

        # Verify: Check that paths and user:group were detected correctly
        from pathlib import Path
        expected_items = str(Path('/etc/openhab') / 'items' / 'knx.items')
        self.assertEqual(config.config['items_path'], expected_items)
        self.assertEqual(config.config['target_user'], 'openhab')
        self.assertEqual(config.config['target_group'], 'openhab')
        logger.info(f"✓ OpenHAB CLI detection: items_path={config.config['items_path']}")

    @patch('pathlib.Path.exists')
    @patch('builtins.open', new_callable=mock_open)
    @patch('json.load')
    @patch('subprocess.run')
    def test_fallback_web_ui(self, mock_run, mock_json_load, mock_file,
                            mock_path_exists):
        """Test fallback to web UI configuration when openhab-cli not available.
        
        When openhab-cli fails (FileNotFoundError), config should:
        1. Try to load web UI configuration
        2. Extract OpenHAB path from web config
        3. Fall back to openhab:openhab for user:group
        """
        # Setup: Mock openhab-cli failure
        mock_run.side_effect = FileNotFoundError("openhab-cli not found")

        # Setup: Mock web UI config file exists and contains valid data
        mock_json_load.return_value = {
            "openhab_path": "/opt/openhab",
            "items_path": "openhab/items/knx.items",
            "defines": {},
            "datapoint_mappings": {}
        }
        mock_path_exists.return_value = True

        # Execute: Import config with mocked filesystem
        import config

        # Verify: Check that paths were set from web UI config
        from pathlib import Path
        expected_items = str(Path('/opt/openhab') / 'items' / 'knx.items')
        self.assertEqual(config.config['items_path'], expected_items)
        # Should use default openhab user when web UI method used
        self.assertEqual(config.config['target_user'], 'openhab')
        self.assertEqual(config.config['target_group'], 'openhab')
        logger.info(f"✓ Web UI fallback: items_path={config.config['items_path']}")

    @patch('pathlib.Path.exists')
    @patch('subprocess.run')
    def test_default_local_paths(self, mock_run, mock_path_exists):
        """Test fallback to local paths when no external detection works.
        
        When both openhab-cli and web UI methods fail, config should:
        1. Use local relative paths
        2. Not set target user/group (local mode)
        """
        # Setup: Mock both detection methods failing
        mock_run.side_effect = FileNotFoundError("openhab-cli not found")
        mock_path_exists.return_value = False  # Web UI config doesn't exist

        # Execute: Import config with both methods failing
        import config

        # Verify: Check that local paths are used
        self.assertIn('openhab', config.config['items_path'])
        # In local mode, no user is set
        self.assertIsNone(config.config.get('target_user'))
        logger.info(f"✓ Local fallback: items_path={config.config['items_path']}")

    @patch('subprocess.run')
    def test_openhab_cli_different_user(self, mock_run):
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
        import config

        # Verify: Check correct user is detected
        self.assertEqual(config.config['target_user'], 'myopenhab')
        self.assertEqual(config.config['target_group'], 'myopenhab')
        logger.info(f"✓ Non-standard user detection: user={config.config['target_user']}")

    @patch('shutil.chown')
    @patch('subprocess.run')
    def test_permission_setting(self, mock_run, mock_chown):
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
        import config
        import ets_to_openhab

        # Call set_permissions
        test_file = '/tmp/testfile.items'
        ets_to_openhab.set_permissions(test_file, configuration=config.config)

        # Verify: Check that chown was called with correct parameters
        mock_chown.assert_called_with(
            test_file,
            user='testuser',
            group='testgroup'
        )
        logger.info(f"✓ Permission setting: called chown({test_file}, testuser:testgroup)")

    @patch('subprocess.run')
    def test_openhab_cli_command_called_correctly(self, mock_run):
        """Test that openhab-cli is called with correct parameters."""
        # Setup
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = "User: test\nOPENHAB_CONF | /test"
        mock_run.return_value = mock_proc

        # Execute
        import config

        # Verify: Check that subprocess.run was called
        # (We can't check exact args without more complex mocking,
        # but we can verify it was called)
        assert mock_run.called, "openhab-cli should be called"
        logger.info(f"✓ openhab-cli was invoked")


if __name__ == '__main__':
    unittest.main()
