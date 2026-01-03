
import unittest
from unittest.mock import patch, MagicMock, mock_open
import sys
import os
import shutil
import json

# Mocking config execution for now by directly testing logic if possible, 
# or by patching subprocess in config.py.
# Since config.py runs on import, we need to be careful.
# Ideally we would refactor config.py to not run main() on import, or reload it.
# But for now, let's try to mock subprocess BEFORE importing config.

class TestOutputConfig(unittest.TestCase):

    def setUp(self):
        # We don't reload here as we need patches active during reload
        pass

    @patch('subprocess.run')
    def test_openhab_cli_detection(self, mock_run):
        # Mock openhab-cli output
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = """
        User:        openhab (Active Process 123)
        User Groups: openhab tty
        Directories: Folder Name      | Path                        | User:Group
                     -----------      | ----                        | ----------
                     OPENHAB_CONF     | /etc/openhab                | openhab:openhab
        """
        mock_run.return_value = mock_proc

        import config
        import importlib
        importlib.reload(config)
        # Verify paths are updated
        from pathlib import Path
        expected = str(Path('/etc/openhab') / 'items' / 'knx.items')
        self.assertEqual(config.config['items_path'], expected)
        self.assertEqual(config.config['target_user'], 'openhab')
        self.assertEqual(config.config['target_group'], 'openhab')

    @patch('subprocess.run')
    def test_fallback_web_ui(self, mock_run):
        # Mock openhab-cli failure
        mock_run.side_effect = FileNotFoundError 
        
        # Mock web_ui config file (merged mock for both config.json and web config to satisfy loading)
        mock_data = {
            "openhab_path": "/opt/openhab",
            "items_path": "openhab/items/knx.items",
            "defines": {}, 
            "datapoint_mappings": {}
        }
        
        with patch("builtins.open", mock_open(read_data=json.dumps(mock_data))) as mock_file:
            with patch("json.load", return_value=mock_data):
                with patch("pathlib.Path.exists", return_value=True):
                     import config
                     import importlib
                     importlib.reload(config)
                     from pathlib import Path
                     expected = str(Path('/opt/openhab') / 'items' / 'knx.items')
                     self.assertEqual(config.config['items_path'], expected)
                     # Should default to openhab:openhab if fallback path found
                     self.assertEqual(config.config['target_user'], 'openhab')
                     self.assertEqual(config.config['target_group'], 'openhab')

    @patch('subprocess.run')
    def test_default_local(self, mock_run):
        mock_run.side_effect = FileNotFoundError
        # Mock path exists false for web ui
        with patch("pathlib.Path.exists", return_value=False):
            import config
            import importlib
            importlib.reload(config)
            self.assertIn('openhab', config.config['items_path']) # Expect openhab/items/knx.items
            self.assertIsNone(config.config['target_user'])

    @patch('shutil.chown')
    def test_permission_setting(self, mock_chown):
        # We need to ensure config is in a known state for this test
        with patch('subprocess.run') as mock_run:
             mock_proc = MagicMock()
             mock_proc.returncode = 0
             mock_proc.stdout = "User: testuser\nUser Groups: testgroup\nOPENHAB_CONF | /tmp/oh"
             mock_run.return_value = mock_proc
             
             # Force reload or re-import within the patch context
             if 'config' in sys.modules:
                 import importlib
                 import config
                 importlib.reload(config)
             else:
                 import config
        
        import ets_to_openhab
        # Force reload ets_to_openhab to ensure it sees the reloaded config
        import importlib
        importlib.reload(ets_to_openhab)
        
        # We invoke set_permissions
        ets_to_openhab.set_permissions('/tmp/testfile')
        
        # Check if chown called with correct user/group
        mock_chown.assert_called_with('/tmp/testfile', user='testuser', group='testgroup')

if __name__ == '__main__':
    unittest.main()
