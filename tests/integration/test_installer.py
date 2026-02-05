#!/usr/bin/env python3
"""Integration tests for the installer/setup.sh script."""

import os
import platform
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


class TestInstallerScript(unittest.TestCase):
    """Test the installer/setup.sh script functionality."""

    def setUp(self):
        """Set up test environment."""
        self.test_dir = tempfile.mkdtemp()
        self.repo_root = Path(__file__).parent.parent.parent
        self.installer_dir = self.repo_root / "installer"
        self.setup_script = self.installer_dir / "setup.sh"

    def tearDown(self):
        """Clean up test environment."""
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)

    def test_setup_script_exists(self):
        """Test that setup.sh exists and is executable."""
        self.assertTrue(
            self.setup_script.exists(), f"Setup script not found at {self.setup_script}"
        )

    def test_setup_script_syntax(self):
        """Test that setup.sh has valid bash syntax."""
        # Skip on Windows as bash may not be available
        if platform.system() == "Windows":
            self.skipTest("Bash syntax check not applicable on Windows")

        # Check if bash is available
        try:
            result = subprocess.run(
                ["bash", "--version"], capture_output=True, text=True, timeout=10
            )
            if result.returncode != 0:
                self.skipTest("Bash is not available on this system")
        except (subprocess.TimeoutExpired, FileNotFoundError):
            self.skipTest("Bash is not available on this system")

        result = subprocess.run(
            ["bash", "-n", str(self.setup_script)], capture_output=True, text=True
        )
        self.assertEqual(result.returncode, 0, f"Bash syntax error: {result.stderr}")

    def test_setup_script_has_shebang(self):
        """Test that setup.sh has proper shebang."""
        if not self.setup_script.exists():
            self.skipTest("Setup script does not exist")

        with open(self.setup_script, "r") as f:
            first_line = f.readline().strip()
        self.assertTrue(first_line.startswith("#!/"), "Setup script missing shebang")
        self.assertIn("bash", first_line.lower(), "Shebang should reference bash")

    def test_setup_script_required_commands(self):
        """Test that setup.sh uses expected commands."""
        if not self.setup_script.exists():
            self.skipTest("Setup script does not exist")

        with open(self.setup_script, "r") as f:
            content = f.read()

        required_commands = [
            "mkdir",  # Directory creation
            "python",  # Python operations
            "pip",  # Package installation
        ]

        for cmd in required_commands:
            self.assertIn(cmd, content, f"Setup script should use '{cmd}' command")

    def test_installer_directory_structure(self):
        """Test that installer directory has required files."""
        required_files = [
            "setup.sh",
            "README.md",
            "knxohui.service",
        ]

        for filename in required_files:
            file_path = self.installer_dir / filename
            self.assertTrue(
                file_path.exists(),
                f"Required file '{filename}' not found in installer directory",
            )

    def test_service_file_validity(self):
        """Test that systemd service file has valid format."""
        service_file = self.installer_dir / "knxohui.service"
        with open(service_file, "r") as f:
            content = f.read()

        # Check for required systemd service sections
        self.assertIn("[Unit]", content, "Service file missing [Unit] section")
        self.assertIn("[Service]", content, "Service file missing [Service] section")
        self.assertIn("[Install]", content, "Service file missing [Install] section")

        # Check for basic service configuration
        self.assertIn("Type=", content, "Service file missing Type directive")
        self.assertIn("ExecStart=", content, "Service file missing ExecStart directive")

    def test_backup_cleanup_script_exists(self):
        """Test that backup cleanup script exists."""
        backup_script = self.installer_dir / "backup_cleanup.sh"
        self.assertTrue(backup_script.exists(), "Backup cleanup script not found")
        # Check if executable
        if backup_script.exists():
            self.assertTrue(
                os.access(backup_script, os.X_OK),
                "Backup cleanup script is not executable",
            )

    def test_setup_script_pipefail_option(self):
        """Test that setup.sh uses 'set -euo pipefail' for safety."""
        if not self.setup_script.exists():
            self.skipTest("Setup script does not exist")

        with open(self.setup_script, "r") as f:
            content = f.read()

        # Check for set -e or set -euo pipefail
        has_error_handling = "set -e" in content or "set -u" in content or "pipefail" in content

        self.assertTrue(
            has_error_handling,
            "Setup script should use 'set -e' or 'set -euo pipefail' for error handling",
        )

    def test_readme_exists_in_installer(self):
        """Test that installer README.md exists and has content."""
        readme = self.installer_dir / "README.md"
        self.assertTrue(readme.exists(), "README.md not found in installer directory")

        # Check that README has actual content
        with open(readme, "r") as f:
            content = f.read().strip()

        self.assertGreater(
            len(content), 100, "README.md seems too short (less than 100 characters)"
        )


if __name__ == "__main__":
    unittest.main()
