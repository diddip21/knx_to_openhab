#!/usr/bin/env python3
"""Provision only generated OpenHAB output files for the service account."""

import argparse
import grp
import os
import pwd
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

import config as generator_config  # noqa: E402
from knxoh_paths import get_paths  # noqa: E402
from web_ui.backend.deploy_policy import (  # noqa: E402
    configured_managed_paths,
    provision_managed_files,
    restrict_service_write_access,
)


def write_protected_openhab_root(config_dir, openhab_root, service_gid):
    """Publish the resolved OpenHAB root for the standalone root helper."""
    config_dir = Path(config_dir)
    openhab_root = Path(openhab_root).resolve()
    if not openhab_root.is_absolute() or any(ch in str(openhab_root) for ch in "\r\n\0"):
        raise ValueError("OpenHAB root must be an absolute path without control characters")

    target = config_dir / "managed_openhab_root"
    descriptor, temporary_path = tempfile.mkstemp(prefix=".managed-openhab-root-", dir=config_dir)
    try:
        os.fchown(descriptor, 0, service_gid)
        os.fchmod(descriptor, 0o640)
        with os.fdopen(descriptor, "w", encoding="utf-8") as destination:
            destination.write(f"{openhab_root}\n")
            destination.flush()
            os.fsync(destination.fileno())
        os.replace(temporary_path, target)
    except Exception:
        try:
            os.close(descriptor)
        except OSError:
            pass
        try:
            os.unlink(temporary_path)
        except FileNotFoundError:
            pass
        raise


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--service-user", default="knxohui")
    parser.add_argument("--openhab-group", default="openhab")
    args = parser.parse_args()

    try:
        service_uid = pwd.getpwnam(args.service_user).pw_uid
        service_gid = grp.getgrnam(args.service_user).gr_gid
        openhab_gid = grp.getgrnam(args.openhab_group).gr_gid
        root, managed = configured_managed_paths(generator_config.config, str(PROJECT_ROOT))
        if not os.path.isdir(root) or os.path.islink(root):
            raise RuntimeError(f"OpenHAB configuration root is not a real directory: {root}")
        restrict_service_write_access(root, service_uid)
        provision_managed_files(root, managed, service_uid, openhab_gid)
        config_dir = os.environ.get("KNXOH_CONFIG_DIR") or get_paths(PROJECT_ROOT).config_dir
        write_protected_openhab_root(config_dir, root, service_gid)
    except (KeyError, OSError, RuntimeError, ValueError) as error:
        print(f"Cannot provision managed OpenHAB outputs: {error}", file=sys.stderr)
        return 1

    print(f"Provisioned {len(set(managed.values()))} managed output files under {root}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
