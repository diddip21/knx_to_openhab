#!/usr/bin/env python3
"""Provision only generated OpenHAB output files for the service account."""

import argparse
import grp
import json
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


def _write_managed_manifest(path, root, managed, group_id):
    """Publish the root-owned allowlist used by managed-output maintenance."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_path = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent, text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as manifest:
            json.dump(
                {"openhab_root": root, "managed_files": managed},
                manifest,
                indent=2,
                sort_keys=True,
            )
            manifest.write("\n")
            manifest.flush()
            os.fsync(manifest.fileno())
        os.chown(temporary_path, 0, group_id)
        os.chmod(temporary_path, 0o640)
        os.replace(temporary_path, path)
    except Exception:
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
        service_gid = pwd.getpwnam(args.service_user).pw_gid
        openhab_gid = grp.getgrnam(args.openhab_group).gr_gid
        root, managed = configured_managed_paths(generator_config.config, str(PROJECT_ROOT))
        if not os.path.isdir(root) or os.path.islink(root):
            raise RuntimeError(f"OpenHAB configuration root is not a real directory: {root}")
        restrict_service_write_access(root, service_uid)
        provision_managed_files(root, managed, service_uid, openhab_gid)
        manifest_path = get_paths(PROJECT_ROOT).config_dir / "managed_outputs.json"
        _write_managed_manifest(manifest_path, root, managed, service_gid)
    except (KeyError, OSError, RuntimeError, ValueError) as error:
        print(f"Cannot provision managed OpenHAB outputs: {error}", file=sys.stderr)
        return 1

    print(f"Provisioned {len(set(managed.values()))} managed output files under {root}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
