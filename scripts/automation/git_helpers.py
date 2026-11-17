"""Git reads used by trusted controllers; never execute candidate code or hooks."""

from __future__ import annotations

import subprocess
from pathlib import Path


def git(*args: str, cwd: Path | None = None) -> str:
    return subprocess.run(
        ["git", "-c", "core.hooksPath=/dev/null", *args],
        cwd=cwd,
        check=True,
        text=True,
        capture_output=True,
    ).stdout.strip()
