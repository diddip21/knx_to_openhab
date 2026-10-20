#!/usr/bin/env python3
"""Provision only generated OpenHAB output files for the service account."""

import argparse
import grp
import os
import pwd
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

import config as generator_config  # noqa: E402
from web_ui.backend.deploy_policy import (  # noqa: E402
    configured_managed_paths,
    provision_managed_files,
)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--service-user", default="knxohui")
    parser.add_argument("--openhab-group", default="openhab")
    args = parser.parse_args()

    try:
        service_uid = pwd.getpwnam(args.service_user).pw_uid
        openhab_gid = grp.getgrnam(args.openhab_group).gr_gid
        root, managed = configured_managed_paths(generator_config.config, str(PROJECT_ROOT))
        if not os.path.isdir(root) or os.path.islink(root):
            raise RuntimeError(f"OpenHAB configuration root is not a real directory: {root}")
        provision_managed_files(root, managed, service_uid, openhab_gid)
    except (KeyError, OSError, RuntimeError, ValueError) as error:
        print(f"Cannot provision managed OpenHAB outputs: {error}", file=sys.stderr)
        return 1

    print(f"Provisioned {len(set(managed.values()))} managed output files under {root}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
