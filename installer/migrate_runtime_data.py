#!/usr/bin/env python3
"""Move legacy Web UI settings and runtime data into canonical external paths."""

from __future__ import annotations

import argparse
import base64
import filecmp
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

LEGACY_RUNTIME_PATHS = {
    "jobs": Path("var/lib/knx_to_openhab"),
    "backups": Path("var/backups/knx_to_openhab"),
}


def _read_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as source:
        value = json.load(source)
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object in {path}")
    return value


def _atomic_write(path: Path, contents: str, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent, text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as destination:
            destination.write(contents)
            destination.flush()
            os.fsync(destination.fileno())
        os.chmod(name, mode)
        os.replace(name, path)
    except Exception:
        try:
            os.unlink(name)
        except FileNotFoundError:
            pass
        raise


def _copy_missing_tree(source: Path, destination: Path) -> None:
    """Copy regular files without following links or replacing existing data."""
    if not source.exists() or source.resolve() == destination.resolve():
        return
    if source.is_symlink() or not source.is_dir():
        raise ValueError(f"Legacy data source must be a real directory: {source}")
    destination.mkdir(parents=True, exist_ok=True)
    try:
        destination_relative = destination.resolve().relative_to(source.resolve())
    except ValueError:
        destination_relative = None
    if destination_relative is not None and len(destination_relative.parts) != 1:
        raise ValueError(
            f"Runtime destination is nested too deeply inside legacy data: {destination}"
        )

    for entry in source.iterdir():
        if destination_relative is not None and entry.name == destination_relative.parts[0]:
            continue
        target = destination / entry.name
        if entry.is_symlink():
            raise ValueError(f"Refusing to copy a symlink from legacy data: {entry}")
        if entry.is_dir():
            _copy_missing_tree(entry, target)
        elif entry.is_file() and target.exists():
            if not target.is_file() or not filecmp.cmp(entry, target, shallow=False):
                raise FileExistsError(f"Legacy data conflicts with existing destination: {target}")
        elif entry.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(entry, target)


def _validate_legacy_source(path: Path, kind: str, source_root: Path) -> None:
    if path == Path(path.anchor):
        raise ValueError(f"Refusing to migrate the filesystem root as {kind}: {path}")
    if path.resolve() == source_root.resolve():
        raise ValueError(f"Refusing to migrate the whole application directory as {kind}: {path}")
    forbidden = {"/etc", "/usr", "/var", "/home", "/root", "/opt", "/tmp"}
    if str(path) in forbidden:
        raise ValueError(f"Refusing to migrate a system directory as {kind}: {path}")
    candidate = Path(path.anchor)
    for component in path.parts[1:]:
        candidate = candidate / component
        if candidate.is_symlink():
            raise ValueError(f"Refusing to follow a symlink in legacy {kind} path: {candidate}")
    try:
        relative = path.relative_to(source_root.resolve())
    except ValueError:
        return
    if relative != LEGACY_RUNTIME_PATHS[kind]:
        raise ValueError(
            f"Refusing to migrate an unexpected in-application {kind} directory: {path}; "
            f"the supported legacy location is {source_root / LEGACY_RUNTIME_PATHS[kind]}"
        )


def _absolute_config_path(value: str, root: Path) -> Path:
    path = Path(os.path.expanduser(value))
    if not path.is_absolute():
        path = root / path
    return Path(os.path.abspath(path))


def _rewrite_job_paths(
    jobs_file: Path, old_jobs: Path, new_jobs: Path, old_backups: Path, new_backups: Path
) -> None:
    if not jobs_file.is_file():
        return
    jobs = _read_json(jobs_file)

    def rewrite(value):
        if not isinstance(value, str) or not value:
            return value
        path = Path(value)
        if not path.is_absolute():
            return value
        resolved = path.resolve(strict=False)
        for old_root, new_root in ((old_jobs, new_jobs), (old_backups, new_backups)):
            try:
                relative = resolved.relative_to(old_root.resolve())
            except ValueError:
                continue
            return str(new_root / relative)
        return value

    for job in jobs.values():
        if not isinstance(job, dict):
            continue
        for key in ("input", "staging_dir"):
            if key in job:
                job[key] = rewrite(job[key])
        for backup in job.get("backups", []):
            if isinstance(backup, dict) and "path" in backup:
                backup["path"] = rewrite(backup["path"])
        mapping = job.get("stage_mapping")
        if isinstance(mapping, dict):
            job["stage_mapping"] = {
                rewrite(source): rewrite(target) for source, target in mapping.items()
            }
        stats = job.get("stats")
        if isinstance(stats, dict):
            for stat_entry in stats.values():
                if isinstance(stat_entry, dict) and "staged_path" in stat_entry:
                    stat_entry["staged_path"] = rewrite(stat_entry["staged_path"])

    _atomic_write(jobs_file, json.dumps(jobs, indent=2, ensure_ascii=False) + "\n", 0o640)


def _write_paths_file(path: Path, values: dict[str, Path]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for key, value in values.items():
        text = str(value)
        if any(ch in text for ch in "\r\n\0"):
            raise ValueError(f"Path contains an unsupported control character: {key}")
        escaped = text.replace("\\", "\\\\").replace('"', '\\"')
        lines.append(f'{key}="{escaped}"')
    _atomic_write(
        path,
        "# Managed by installer/setup.sh; do not edit by hand.\n" + "\n".join(lines) + "\n",
        0o644,
    )


def _template_contents(source_root: Path, template_root: Path, relative_path: str) -> str | None:
    template_file = template_root / relative_path
    if source_root != template_root and template_file.is_file():
        return template_file.read_text(encoding="utf-8")
    result = subprocess.run(
        ["git", "show", f"HEAD:{relative_path}"],
        cwd=source_root,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout if result.returncode == 0 else None


def migrate_runtime_data(
    source_root: Path,
    template_root: Path,
    config_dir: Path,
    data_dir: Path,
    backup_dir: Path,
    install_dir: Path,
    paths_file: Path,
) -> dict[str, Path]:
    source_root = source_root.resolve()
    template_root = template_root.resolve()
    config_dir = config_dir.resolve()
    data_dir = data_dir.resolve()
    backup_dir = backup_dir.resolve()
    install_dir = install_dir.resolve()

    app_config_target = config_dir / "config.json"
    generator_config_target = data_dir / "generator.json"
    legacy_generator_config = config_dir / "generator.json"
    secrets_target = config_dir / "secrets.env"
    for target in (
        app_config_target,
        generator_config_target,
        legacy_generator_config,
        secrets_target,
    ):
        if target.is_symlink():
            raise ValueError(
                f"Refusing to replace a symlink in the configuration directory: {target}"
            )
    legacy_app_candidates = (
        source_root / "web_ui" / "backend" / "config.json",
        template_root / "web_ui" / "backend" / "config.json",
    )
    legacy_app_path = next((p for p in legacy_app_candidates if p.is_file()), None)
    if app_config_target.is_file():
        runtime_config = _read_json(app_config_target)
    elif legacy_app_path:
        runtime_config = _read_json(legacy_app_path)
    else:
        runtime_config = {}

    old_jobs = _absolute_config_path(
        str(runtime_config.get("jobs_dir", "var/lib/knx_to_openhab")), source_root
    )
    old_backups = _absolute_config_path(
        str(runtime_config.get("backups_dir", "var/backups/knx_to_openhab")), source_root
    )
    new_jobs = data_dir / "jobs"
    new_staging = data_dir / "staging"
    new_generated = data_dir / "generated"

    config_dir.mkdir(parents=True, exist_ok=True)
    for directory in (new_jobs, new_staging, new_generated, backup_dir):
        directory.mkdir(parents=True, exist_ok=True)

    _validate_legacy_source(old_jobs, "jobs", source_root)
    _validate_legacy_source(old_backups, "backups", source_root)
    _copy_missing_tree(old_jobs, new_jobs)
    _copy_missing_tree(old_backups, backup_dir)

    if not generator_config_target.exists():
        if legacy_generator_config.is_file():
            shutil.copy2(legacy_generator_config, generator_config_target)
            os.chmod(generator_config_target, 0o660)
        else:
            generator_sources = (source_root / "config.json", template_root / "config.json")
            generator_source = next((p for p in generator_sources if p.is_file()), None)
            if not generator_source:
                raise FileNotFoundError("No generator config.json was found to migrate")
            shutil.copy2(generator_source, generator_config_target)
            os.chmod(generator_config_target, 0o660)

    if not app_config_target.exists():
        if legacy_app_path:
            shutil.copy2(legacy_app_path, app_config_target)
        else:
            app_config_target.write_text("{}\n", encoding="utf-8")

    runtime_config = _read_json(app_config_target)
    auth = runtime_config.setdefault("auth", {})
    if not isinstance(auth, dict):
        raise ValueError("Web UI auth configuration must be an object")
    password = auth.pop("password", None)
    secret_lines = (
        secrets_target.read_text(encoding="utf-8").splitlines() if secrets_target.exists() else []
    )
    has_password_secret = any(line.startswith("KNXOH_UI_PASSWORD_B64=") for line in secret_lines)
    if password is not None and not has_password_secret:
        encoded = base64.b64encode(str(password).encode("utf-8")).decode("ascii")
        secret_lines.append(f"KNXOH_UI_PASSWORD_B64={encoded}")
        _atomic_write(secrets_target, "\n".join(secret_lines) + "\n", 0o640)
    elif not secrets_target.exists():
        _atomic_write(secrets_target, "", 0o640)
    os.chmod(secrets_target, 0o640)

    runtime_config.update(
        {
            "jobs_dir": str(new_jobs),
            "staging_dir": str(new_staging),
            "generated_dir": str(new_generated),
            "backups_dir": str(backup_dir),
        }
    )

    values = {
        "KNXOH_INSTALL_DIR": install_dir,
        "KNXOH_CONFIG_DIR": config_dir,
        "KNXOH_DATA_DIR": data_dir,
        "KNXOH_BACKUP_DIR": backup_dir,
    }
    _write_paths_file(paths_file, values)

    # Publish canonical paths only after all data is copied, and rewrite the
    # job index before removing legacy data. If path publication fails, both
    # the old configuration and its source data remain usable for a retry.
    _rewrite_job_paths(new_jobs / "jobs.json", old_jobs, new_jobs, old_backups, backup_dir)

    _atomic_write(
        app_config_target, json.dumps(runtime_config, indent=2, ensure_ascii=False) + "\n", 0o640
    )
    os.chmod(app_config_target, 0o640)
    os.chmod(generator_config_target, 0o660)

    # Once the external copies and references are complete, remove only legacy
    # state that lived inside the application tree. Keep custom external sources.
    for legacy, destination in ((old_jobs, new_jobs), (old_backups, backup_dir)):
        try:
            legacy.resolve().relative_to(source_root)
            inside_install = True
        except ValueError:
            inside_install = False
        try:
            destination.resolve().relative_to(legacy.resolve())
            destination_inside_source = True
        except ValueError:
            destination_inside_source = False
        if inside_install and not destination_inside_source and legacy.exists():
            shutil.rmtree(legacy)

    source_generator = source_root / "config.json"
    generator_template = _template_contents(source_root, template_root, "config.json")
    if source_generator.is_file() and generator_template is not None:
        _atomic_write(source_generator, generator_template, 0o640)

    return values


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--template-root", type=Path, required=True)
    parser.add_argument("--config-dir", type=Path, required=True)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--backup-dir", type=Path, required=True)
    parser.add_argument("--install-dir", type=Path, required=True)
    parser.add_argument("--paths-file", type=Path, default=Path("/etc/knx_to_openhab/paths.env"))
    args = parser.parse_args()
    migrate_runtime_data(
        args.source_root,
        args.template_root,
        args.config_dir,
        args.data_dir,
        args.backup_dir,
        args.install_dir,
        args.paths_file,
    )


if __name__ == "__main__":
    main()
