"""Canonical installation paths with a repository-local development fallback."""

from __future__ import annotations

import os
import shlex
from dataclasses import dataclass
from pathlib import Path

PATHS_FILE = Path("/etc/knx_to_openhab/paths.env")
PATH_ENV_KEYS = {
    "KNXOH_INSTALL_DIR",
    "KNXOH_CONFIG_DIR",
    "KNXOH_DATA_DIR",
    "KNXOH_BACKUP_DIR",
    "KNXOH_PATHS_FILE",
}


def load_saved_path_environment() -> None:
    """Load installer-owned path values without evaluating a shell file."""
    path_file = Path(os.environ.get("KNXOH_PATHS_FILE", PATHS_FILE))
    try:
        lines = path_file.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        name, raw_value = stripped.split("=", 1)
        if name not in PATH_ENV_KEYS or name in os.environ:
            continue
        try:
            parsed = shlex.split(raw_value, posix=True)
        except ValueError:
            continue
        if len(parsed) == 1:
            os.environ[name] = parsed[0]


@dataclass(frozen=True)
class InstallPaths:
    project_root: Path
    install_dir: Path
    config_dir: Path
    data_dir: Path
    backup_dir: Path
    web_config_file: Path
    generator_config_file: Path
    secrets_file: Path | None
    jobs_dir: Path
    staging_dir: Path
    generated_dir: Path


def get_paths(project_root: str | Path | None = None) -> InstallPaths:
    """Return consistent paths for production or the existing local dev layout."""
    load_saved_path_environment()
    root = Path(project_root or Path(__file__).resolve().parent).resolve()
    external_config = bool(os.environ.get("KNXOH_CONFIG_DIR"))

    install_dir = Path(os.environ.get("KNXOH_INSTALL_DIR", root)).expanduser()
    config_dir = Path(
        os.environ.get(
            "KNXOH_CONFIG_DIR",
            root / "web_ui" / "backend",
        )
    ).expanduser()
    data_dir = Path(
        os.environ.get("KNXOH_DATA_DIR", root / "var" / "lib" / "knx_to_openhab")
    ).expanduser()
    backup_dir = Path(
        os.environ.get("KNXOH_BACKUP_DIR", root / "var" / "backups" / "knx_to_openhab")
    ).expanduser()

    web_config_file = config_dir / "config.json"
    generator_config_file = data_dir / "generator.json" if external_config else root / "config.json"
    secrets_file = config_dir / "secrets.env" if external_config else None
    jobs_dir = data_dir / "jobs" if external_config else data_dir
    staging_dir = data_dir / "staging" if external_config else jobs_dir
    generated_dir = data_dir / "generated"

    return InstallPaths(
        project_root=root,
        install_dir=install_dir.resolve(),
        config_dir=config_dir.resolve(),
        data_dir=data_dir.resolve(),
        backup_dir=backup_dir.resolve(),
        web_config_file=web_config_file.resolve(),
        generator_config_file=generator_config_file.resolve(),
        secrets_file=secrets_file.resolve() if secrets_file else None,
        jobs_dir=jobs_dir.resolve(),
        staging_dir=staging_dir.resolve(),
        generated_dir=generated_dir.resolve(),
    )
