"""Execute the real JavaScript publisher against a deterministic fake GitHub API."""

import shutil
import subprocess

import pytest

from .helpers import ROOT


@pytest.mark.parametrize("test_file", sorted((ROOT / "tests/ai_pipeline").glob("*.test.cjs")))
def test_node_publisher_and_readiness_contracts(test_file):
    if shutil.which("node") is None:
        pytest.skip("Node.js is required; the dedicated guard workflow installs Node 22")
    result = subprocess.run(
        ["node", "--test", str(test_file)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
