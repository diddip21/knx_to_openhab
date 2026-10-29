"""Safely resolve the configured paths used by the uninstaller."""

from __future__ import annotations

import argparse
import os
import posixpath
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Callable, Mapping, Sequence, TextIO

PATH_DEFAULTS = {
    "KNXOH_INSTALL_DIR": "/opt/knx_to_openhab",
    "KNXOH_CONFIG_DIR": "/etc/knx_to_openhab",
    "KNXOH_DATA_DIR": "/var/lib/knx_to_openhab",
    "KNXOH_BACKUP_DIR": "/var/backups/knx_to_openhab",
}
PATHS_FILE = Path("/etc/knx_to_openhab/paths.env")
PROTECTED_DIRECTORIES = {
    PurePosixPath("/"),
    PurePosixPath("/etc"),
    PurePosixPath("/usr"),
    PurePosixPath("/var"),
    PurePosixPath("/opt"),
    PurePosixPath("/home"),
    PurePosixPath("/root"),
    PurePosixPath("/tmp"),
    PurePosixPath("/run"),
}


class UninstallError(ValueError):
    """Raised when an install path is unsafe or malformed."""


@dataclass(frozen=True)
class UninstallPaths:
    install_dir: PurePosixPath
    config_dir: PurePosixPath
    data_dir: PurePosixPath
    backup_dir: PurePosixPath


@dataclass(frozen=True)
class RemovalAction:
    description: str
    command: tuple[str, ...]
    best_effort: bool = False


def _read_saved_paths(paths_file: Path) -> dict[str, str]:
    try:
        lines = paths_file.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return {}
    except OSError as error:
        raise UninstallError(
            f"Cannot read saved path configuration {paths_file}: {error}"
        ) from error

    saved: dict[str, str] = {}
    for line_number, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        name, raw_value = stripped.split("=", 1)
        if name not in PATH_DEFAULTS:
            continue
        if name in saved:
            raise UninstallError(f"Duplicate {name} in {paths_file}:{line_number}")
        try:
            values = shlex.split(raw_value, posix=True)
        except ValueError as error:
            raise UninstallError(
                f"Invalid quoting for {name} in {paths_file}:{line_number}"
            ) from error
        if len(values) != 1 or not values[0]:
            raise UninstallError(
                f"Expected one non-empty path for {name} in {paths_file}:{line_number}"
            )
        saved[name] = values[0]
    return saved


def _parse_path(name: str, value: str) -> PurePosixPath:
    if not value or any(character in value for character in "\r\n\0"):
        raise UninstallError(f"{name} must be a non-empty path without control characters")
    if not value.startswith("/"):
        raise UninstallError(f"{name} must be an absolute path: {value}")
    raw_parts = value.split("/")
    if ".." in raw_parts:
        raise UninstallError(f"{name} must not contain parent traversal: {value}")
    normalized = PurePosixPath(posixpath.normpath(value))
    if normalized == PurePosixPath("/"):
        raise UninstallError(f"Refusing to use the filesystem root as {name}")
    if normalized in PROTECTED_DIRECTORIES:
        raise UninstallError(f"Refusing to use a system directory as {name}: {normalized}")

    if os.name == "posix":
        candidate = Path("/")
        for component in normalized.parts[1:]:
            candidate = candidate / component
            if candidate.is_symlink():
                raise UninstallError(f"Refusing symlinked {name}: {candidate}")
    return normalized


def _overlaps(left: PurePosixPath, right: PurePosixPath) -> bool:
    return left == right or left in right.parents or right in left.parents


def resolve_uninstall_paths(
    env: Mapping[str, str], paths_file: Path = PATHS_FILE
) -> UninstallPaths:
    """Resolve path overrides and saved installer paths without running a shell."""
    saved = _read_saved_paths(Path(paths_file))
    resolved = {
        name: _parse_path(name, env.get(name, saved.get(name, default)))
        for name, default in PATH_DEFAULTS.items()
    }

    install_dir = resolved["KNXOH_INSTALL_DIR"]
    external_dirs = (
        resolved["KNXOH_CONFIG_DIR"],
        resolved["KNXOH_DATA_DIR"],
        resolved["KNXOH_BACKUP_DIR"],
    )
    named_external_dirs = (
        ("configuration", external_dirs[0]),
        ("runtime data", external_dirs[1]),
        ("backups", external_dirs[2]),
    )
    for index, (left_name, left) in enumerate(named_external_dirs):
        if _overlaps(install_dir, left):
            raise UninstallError(f"The {left_name} path overlaps the application directory: {left}")
        for right_name, right in named_external_dirs[index + 1 :]:
            if _overlaps(left, right):
                raise UninstallError(
                    f"The {left_name} path overlaps the {right_name} path: {left}, {right}"
                )

    return UninstallPaths(
        install_dir=install_dir,
        config_dir=resolved["KNXOH_CONFIG_DIR"],
        data_dir=resolved["KNXOH_DATA_DIR"],
        backup_dir=resolved["KNXOH_BACKUP_DIR"],
    )


def _removal_actions(paths: UninstallPaths, purge: bool) -> list[RemovalAction]:
    units = (
        "knxohui-update.service",
        "knxohui.service",
        "knxohui-backup-cleanup.service",
        "knxohui-backup-cleanup.timer",
        "knxohui-update-recovery.service",
    )
    actions = [
        RemovalAction(f"Stop {unit}", ("sudo", "systemctl", "stop", unit), best_effort=True)
        for unit in units
    ]
    actions.extend(
        RemovalAction(f"Disable {unit}", ("sudo", "systemctl", "disable", unit), best_effort=True)
        for unit in units
    )
    actions.extend(
        (
            RemovalAction(
                "Remove systemd units",
                (
                    "sudo",
                    "rm",
                    "-f",
                    "--",
                    "/etc/systemd/system/knxohui.service",
                    "/etc/systemd/system/knxohui-backup-cleanup.service",
                    "/etc/systemd/system/knxohui-backup-cleanup.timer",
                ),
            ),
            RemovalAction(
                "Remove restricted sudoers policy",
                ("sudo", "rm", "-f", "--", "/etc/sudoers.d/knxohui"),
            ),
            RemovalAction("Reload systemd units", ("sudo", "systemctl", "daemon-reload")),
        )
    )
    if purge:
        # No journal/previous release/bundle may be destroyed implicitly. The
        # installed fixed CLI's validation is not a lease for later rm commands.
        # Therefore purge is deliberately refused below whenever updater state
        # exists; administrator recovery + explicit evidence archival is required.
        actions.extend(
            (
                RemovalAction(
                    f"Purge configuration at {paths.config_dir}",
                    ("sudo", "rm", "-rf", "--", str(paths.config_dir)),
                ),
                RemovalAction(
                    f"Purge runtime data at {paths.data_dir}",
                    ("sudo", "rm", "-rf", "--", str(paths.data_dir)),
                ),
                RemovalAction(
                    f"Purge backups at {paths.backup_dir}",
                    ("sudo", "rm", "-rf", "--", str(paths.backup_dir)),
                ),
                RemovalAction(
                    f"Purge application releases at {paths.install_dir}",
                    ("sudo", "rm", "-rf", "--", str(paths.install_dir)),
                ),
                RemovalAction(
                    "Remove service account",
                    ("sudo", "userdel", "knxohui"),
                    best_effort=True,
                ),
            )
        )
    return actions


def _default_command_runner(command: Sequence[str]) -> int:
    try:
        return subprocess.run(list(command), check=False).returncode
    except OSError as error:
        print(f"Could not run {command[0]}: {error}", file=sys.stderr)
        return 127


def _print_plan(paths: UninstallPaths, purge: bool, output: TextIO) -> None:
    output.write("Planned uninstall actions:\n")
    for action in _removal_actions(paths, purge):
        output.write(f"  - {action.description}\n")
        if len(action.command) > 4 and action.command[1] == "rm":
            for target in action.command[4:]:
                output.write(f"    Path: {target}\n")
    if purge:
        output.write("  - Configuration, jobs, runtime data, and backups will be deleted.\n")
        output.write(f"    Configuration: {paths.config_dir}\n")
        output.write(f"    Runtime data: {paths.data_dir}\n")
        output.write(f"    Backups: {paths.backup_dir}\n")
    else:
        output.write(
            "  - Protected updater/recovery units, bundle, releases, preparation evidence, "
            "paths and both service accounts will be retained for offline recovery.\n"
        )
        output.write("  - Configuration, jobs, runtime data, and backups will be retained.\n")
        output.write(f"    Configuration: {paths.config_dir}\n")
        output.write(f"    Runtime data: {paths.data_dir}\n")
        output.write(f"    Backups: {paths.backup_dir}\n")
        output.write(
            "  - The knxohui service account will be retained to preserve file ownership.\n"
        )


def run_uninstall(
    argv: Sequence[str] | None = None,
    *,
    env: Mapping[str, str] | None = None,
    paths_file: Path | None = None,
    confirm: Callable[[str], str] = input,
    command_runner: Callable[[Sequence[str]], int] = _default_command_runner,
    output: TextIO = sys.stdout,
) -> int:
    """Run the confirmed, idempotent uninstall or purge lifecycle."""
    parser = argparse.ArgumentParser(description="Safely remove KNX to OpenHAB")
    parser.add_argument(
        "--purge",
        action="store_true",
        help="also permanently delete external config, runtime data, backups, and service account",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)
    environment = os.environ if env is None else env
    saved_paths = paths_file or Path(environment.get("KNXOH_PATHS_FILE", PATHS_FILE))
    try:
        paths = resolve_uninstall_paths(environment, saved_paths)
    except UninstallError as error:
        output.write(f"Refusing to uninstall: {error}\n")
        return 2

    _print_plan(paths, args.purge, output)
    try:
        response = confirm("Type UNINSTALL to continue: ")
    except EOFError:
        response = ""
    if response != "UNINSTALL":
        output.write("Uninstallation cancelled; no changes were made.\n")
        return 0

    if args.purge:
        try:
            response = confirm("Type PURGE to permanently delete the listed user data: ")
        except EOFError:
            response = ""
        if response != "PURGE":
            output.write("Purge cancelled; no changes were made.\n")
            return 0

    actions = _removal_actions(paths, args.purge)
    failures: list[str] = []
    purge_actions_started = False
    purge_checked = False
    for action in actions:
        if args.purge and not purge_checked and "rm" in action.command:
            # Stop/disable writers FIRST. Private evidence is checked as root,
            # without reading it into the unprivileged uninstaller. A managed
            # updater installation itself also blocks legacy purge: a separate
            # CLI clean-state check would not reserve a lease for later rm.
            for retained in (
                str(paths.config_dir / ".updater-state"),
                "/usr/local/libexec/knx_to_openhab/update_release.py",
                "/etc/systemd/system/knxohui-update.service",
            ):
                absent = command_runner(("sudo", "test", "!", "-e", retained)) == 0
                no_link = command_runner(("sudo", "test", "!", "-L", retained)) == 0
                if not absent or not no_link:
                    output.write(
                        "Purge refused: retain updater recovery evidence; run installed offline "
                        "recovery and arrange explicit administrator archival first.\n"
                    )
                    return 2
            purge_checked = True
        if (
            action.description.startswith("Purge ")
            or action.description == "Remove service account"
        ):
            purge_actions_started = True
        status = command_runner(action.command)
        if status != 0 and not action.best_effort:
            failures.append(action.description)
            # Stop at the first failed required action. In particular, never
            # continue deleting other user-data trees after a partial purge.
            break
    if failures:
        output.write("Uninstallation finished with errors: " + "; ".join(failures) + "\n")
        if args.purge and purge_actions_started:
            output.write("Purge may be partial; inspect the configured paths before retrying.\n")
        else:
            output.write("External configuration, runtime data, and backups were retained.\n")
        return 1

    if args.purge:
        output.write("Uninstallation and purge complete; configured user data was deleted.\n")
    else:
        output.write(
            "Uninstallation complete; configuration, runtime data, and backups were retained.\n"
        )
    return 0


def main() -> int:
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        print(
            "Run this uninstaller as a regular user with sudo access, not as root.", file=sys.stderr
        )
        return 2
    return run_uninstall()


if __name__ == "__main__":
    raise SystemExit(main())
