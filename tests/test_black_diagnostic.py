import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_black_release_selection_diagnostic():
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "black",
            "--check",
            "--diff",
            str(ROOT / "tests/test_release_selection.py"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
