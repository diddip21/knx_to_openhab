"""Allowlisted host adapter for the real setup recovery tests; never use on a host."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

root = Path(os.environ["SETUP_SANDBOX"]).resolve()
args = sys.argv[1:]
with (root / "commands.jsonl").open("a") as log:
    log.write(json.dumps(args) + "\n")
fault = os.environ.get("SETUP_FAULT", "")


def local(value):
    path = Path(value).resolve()
    if not path.is_relative_to(root):
        raise RuntimeError(f"Refusing path outside sandbox: {path}")
    return path


def execute(command):
    os.execvpe(command[0], command, os.environ)


if args[:2] == ["-n", "true"]:
    sys.exit(0)
if args[:2] == ["-u", "knxohui"]:
    args = args[2:]
command = args[0]
if command == "systemctl":
    state_file = root / "active.json"
    active = json.loads(state_file.read_text())
    action, unit = args[1], args[-1]
    if action == "is-active":
        sys.exit(0 if unit in active else 3)
    if action == "show":
        print(
            "loaded"
            if "--property=LoadState" in args
            else "active" if unit in active else "inactive"
        )
    elif action in {"start", "restart", "stop"}:
        if action == "restart" and fault == "restart":
            sys.exit(73)
        if action == "stop":
            active = [value for value in active if value != unit]
        elif unit not in active:
            active.append(unit)
        state_file.write_text(json.dumps(active))
    elif action not in {"list-jobs", "daemon-reload", "enable"}:
        raise RuntimeError(f"Unexpected systemctl action: {args}")
elif command == "install":
    rewritten = []
    for value in args[1:]:
        if value in {"knxohui", "root"}:
            rewritten.append("root")
        elif value.startswith(("/usr/local/", "/etc/")):
            rewritten.append(str(root / "host" / value.lstrip("/")))
        else:
            if value.startswith("/"):
                local(value)
            rewritten.append(value)
    if fault == "helpers" and args[-1].endswith("/launch_backup_cleanup.sh"):
        sys.exit(71)
    sys.exit(subprocess.call(["/usr/bin/install", *rewritten]))
elif command in {"chown", "chmod", "usermod", "systemd-tmpfiles"}:
    pass  # Ownership, account membership and host tmpfiles are outside this test.
elif command == "mkdir":
    for value in args[1:]:
        if not value.startswith("-"):
            local(value).mkdir(parents=True, exist_ok=True)
elif command == "env":
    # The fixture precreates a real root-owned lock instead of provisioning a user.
    if "ensure_maintenance_lock" not in " ".join(args):
        raise RuntimeError(f"Unexpected env invocation: {args}")
elif command == "bash":
    script = local(args[1])
    if script.name != "migrate_sudoers.sh":
        if script.name not in {
            "hold_updater_locks.sh",
            "quiesce_systemd_unit.sh",
            "quiesce_update_service.sh",
        }:
            raise RuntimeError(f"Unexpected shell script: {script}")
        execute(args)
elif command == "kill":
    execute(args)
elif command == "rsync":
    source, destination = local(args[-2]), local(args[-1])
    for child in source.iterdir():
        if child.name in {"config.json", "venv", ".git"}:
            continue
        target = destination / child.name
        if child.is_dir():
            shutil.copytree(
                child,
                target,
                dirs_exist_ok=True,
                ignore=shutil.ignore_patterns("config.json") if child.name == "web_ui" else None,
            )
        else:
            shutil.copy2(child, target)
elif command == "python3" or command.endswith("/venv/bin/python"):
    if args[1:3] == ["-m", "venv"]:
        local(args[3])  # The fixture already supplies the interpreter and pip stub.
    else:
        script = local(args[1])
        if script.name in {"migrate_runtime_data.py", "configure_auth.py"}:
            registry = root / "registry" / "paths.env"
            if fault == "migration" and script.name == "migrate_runtime_data.py":
                previous = registry.read_bytes()
                registry.unlink()
                registry.mkdir()
                try:
                    sys.exit(subprocess.call(args))
                finally:
                    registry.rmdir()
                    registry.write_bytes(previous)
            execute(args)
        elif script.name not in {
            "write_maintenance_lock_tmpfiles.py",
            "configure_bind.py",
            "provision_managed_files.py",
        }:
            raise RuntimeError(f"Unexpected Python script: {script}")
elif command.endswith("/venv/bin/pip"):
    local(command)
else:
    raise RuntimeError(f"Unexpected privileged command: {args}")
