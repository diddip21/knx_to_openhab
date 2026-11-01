import subprocess
import sys
from pathlib import Path


def test_show_black_diff_for_uninstall_mode_tests():
    target = Path(__file__).with_name("test_uninstall_modes.py")
    result = subprocess.run(
        [sys.executable, "-m", "black", "--diff", str(target)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
