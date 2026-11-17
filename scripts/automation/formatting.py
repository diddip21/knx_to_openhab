"""Format only bounded approved Python text using trusted configuration."""

import subprocess
import sys
from pathlib import Path
from typing import Any

from . import artifacts
from .scope import validate_paths


def format_candidate(root: Path, trusted: Path, context: dict[str, Any], *, repair: bool) -> None:
    paths = artifacts.changed_paths(root, check_whitespace=False)
    validate_paths(paths, context["scope"], repair=repair)
    python_files = []
    for path in paths:
        artifacts.file_bytes(root, path)
        mode, _ = artifacts.base_file(root, path)
        if mode is None and (repair or path not in context["scope"]["create"]):
            raise ValueError("Formatting cannot authorize a new file")
        if path.endswith(".py"):
            python_files.append(str(root / path))
    if not python_files:
        return
    config = str(trusted / "pyproject.toml")
    # Explicit config and filenames prevent candidate config discovery or imports.
    subprocess.run(
        [sys.executable, "-I", "-m", "isort", "--settings-path", config, "--", *python_files],
        cwd=trusted,
        check=True,
        timeout=120,
    )
    subprocess.run(
        [sys.executable, "-I", "-m", "black", "--config", config, "--", *python_files],
        cwd=trusted,
        check=True,
        timeout=120,
    )
    artifacts.collect(context, root, repair=repair)
