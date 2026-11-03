import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

INTENTIONAL_KNX_FILES = (
    "tests/Charne.knxproj.json",
    "tests/fixtures/Charne.knxproj",
    "tests/upload.knxprojarchive.json",
)


@pytest.mark.parametrize("relative_path", INTENTIONAL_KNX_FILES)
def test_intentional_knx_fixtures_are_not_ignored(relative_path):
    if shutil.which("git") is None or not (ROOT / ".git").exists():
        pytest.skip("Git checkout required to verify ignore rules")
    assert (ROOT / relative_path).is_file(), f"missing intentional fixture: {relative_path}"

    result = subprocess.run(
        ["git", "check-ignore", "--no-index", "--quiet", "--", relative_path],
        cwd=ROOT,
        check=False,
    )

    assert result.returncode == 1, f"{relative_path} is ignored but intentionally tracked"
