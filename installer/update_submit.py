"""Unprivileged protocol-1 publisher, shared by the API and compatibility CLI.

This is APPLICATION code, not part of the trusted root-installed bundle. The only
privileged command it requests is the exact nonblocking fixed-unit start. Public
status is acknowledgement, never authority to recover a protected transaction.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import subprocess
import time
from contextlib import contextmanager
from dataclasses import asdict
from uuid import uuid4

from .update_core import secure_fs as fs
from .update_core.artifacts import _read_entry
from .update_core.protocol import Limits, Paths, parse_object, parse_request
from .update_core.state import PHASES, TERMINAL
from .update_core.transaction import UpdateResult

ACK_TIMEOUT = 30.0
STALE_SECONDS = 30.0
POLL_INTERVAL = 0.1
COMMAND_TIMEOUT_SECONDS = 5
# Two manager inspections, one nonblocking start, then the FULL claim window.
SUBMISSION_WAIT_SECONDS = 3 * COMMAND_TIMEOUT_SECONDS + ACK_TIMEOUT
UNIT = "knxohui-update.service"
SYSTEMCTL = "/usr/bin/systemctl"
SETUP = (
    "Verified release updater unavailable. Run the verified administrator bootstrap "
    "(install.sh --repair for a managed installation); legacy/development layouts "
    "need one-time verified installation with external configuration and credentials."
)
RECOVERY = "Update was claimed but did not complete; use installed offline recovery or verified administrator bootstrap."


def validate_channel(channel: str) -> str:
    if not isinstance(channel, str) or channel not in ("stable", "prerelease"):
        raise ValueError("channel must be stable or prerelease")
    return channel


def read_status(paths: Paths) -> dict:
    # A legitimate coordinator replaces this projection atomically while clients
    # poll. Discard raced bytes and retry a bounded full no-follow/owner-checked
    # read, rather than turning a successful claim into a submission failure.
    # Invalid content/ownership/mounts are NOT retryable or relaxed.
    for attempt in range(3):
        try:
            raw = fs.read_regular(paths.config_dir / ".updater-status.json", 4096)
            break
        except fs.EntryChangedError:
            if attempt == 2:
                raise
            time.sleep(0.01)
    value = parse_object(raw, 4096)
    if (
        set(value)
        not in (
            {"format_version", "phase", "message"},
            {"format_version", "phase", "message", "request_id"},
        )
        or type(value["format_version"]) is not int
        or value["format_version"] != 1
        or not isinstance(value["phase"], str)
        or value["phase"] not in PHASES
        or not isinstance(value["message"], str)
        or not value["message"]
        or len(value["message"].encode()) > 1024
        or any(ord(c) < 32 or ord(c) == 127 for c in value["message"])
    ):
        raise ValueError("Invalid updater status")
    if "request_id" in value:
        parse_request(
            json.dumps(
                {"format_version": 1, "request_id": value["request_id"], "channel": "stable"}
            ).encode()
        )
    return value


def _worker_state() -> str:
    result = subprocess.run(
        [
            SYSTEMCTL,
            "show",
            UNIT,
            "--property=LoadState,ActiveState,SubState,Job",
            "--all",
            "--no-pager",
        ],
        capture_output=True,
        text=True,
        timeout=COMMAND_TIMEOUT_SECONDS,
        check=False,
        env={"PATH": "/usr/bin:/bin", "LANG": "C"},
    )
    if result.returncode or len(result.stdout) > 4096:
        raise ValueError(SETUP)
    values = {}
    for line in result.stdout.splitlines():
        key, sep, value = line.partition("=")
        if not sep or key in values:
            raise ValueError(SETUP)
        values[key] = value
    if (
        set(values) != {"LoadState", "ActiveState", "SubState", "Job"}
        or values["LoadState"] != "loaded"
    ):
        raise ValueError(SETUP)
    # systemctl renders the D-Bus (0, "/") empty Job as "Job=" (use --all).
    if values["Job"] not in ("", "0"):
        if values["Job"].isdigit() and int(values["Job"]) > 0:
            return "active"
        raise ValueError(SETUP)
    if (values["ActiveState"], values["SubState"]) in (("inactive", "dead"), ("failed", "failed")):
        return "inactive"
    if values["ActiveState"] in ("active", "activating", "deactivating", "reloading"):
        return "active"
    raise ValueError(SETUP)


def _managed(paths):
    if paths.config_dir is None or paths.data_dir is None:
        raise ValueError(SETUP)
    if paths.current != paths.releases.parent / "current":
        raise ValueError(SETUP)
    # Do not silently convert flat installs, follow release/config/data symlinks,
    # or accept a current link outside the administrator-owned releases parent.
    with fs._parent(paths.releases) as (stack, parent, name, chain):
        releases = fs._open(stack, parent, name, {0}, None, directory=True)
        target = paths.current.resolve(strict=True)
        if target.parent != paths.releases or not paths.current.is_symlink():
            raise ValueError(SETUP)
        entry = fs._open(stack, releases.fd, target.name, {0}, releases.info.st_dev, directory=True)
        fs._check([*chain, releases, entry])
    read_status(paths)


@contextmanager
def _submission_lock(paths):
    import fcntl

    uid = os.geteuid()
    with fs._parent(paths.data_dir) as (stack, parent, name, chain):
        data = fs._open(stack, parent, name, {uid}, None, directory=True)
        try:
            os.mkdir("update", mode=0o700, dir_fd=data.fd)
            os.fsync(data.fd)
        except FileExistsError:
            pass
        update = fs._open(stack, data.fd, "update", {uid}, data.info.st_dev, directory=True)
        fd = os.open(
            "submit.lock",
            os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK,
            0o600,
            dir_fd=update.fd,
        )
        stack.callback(os.close, fd)
        info = os.fstat(fd)
        fs._validate(info, {uid}, data.info.st_dev)
        lock = fs._Entry(fd, update.fd, "submit.lock", info)
        entries = [*chain, data, update, lock]
        fs._check(entries)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        # Never unlink/recreate this inode, including on exceptions or process exit.
        fs._check(entries)
        yield stack, update, entries


def _existing(stack, update):
    try:
        entry = fs._open(stack, update.fd, "request.json", {os.geteuid()}, update.info.st_dev)
    except FileNotFoundError:
        return None, None
    return entry, parse_request(_read_entry(entry, Limits.REQUEST_BYTES))


def _rename_no_replace(parent, source, destination):
    """Atomic publication without a two-hardlink crash window or clobber fallback."""
    import ctypes

    libc = ctypes.CDLL(None, use_errno=True)
    try:
        rename = libc.renameat2
    except AttributeError as error:
        raise NotImplementedError("Linux renameat2 is required for safe submission") from error
    rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    rename.restype = ctypes.c_int
    if rename(parent, os.fsencode(source), parent, os.fsencode(destination), 1):  # RENAME_NOREPLACE
        error = ctypes.get_errno()
        raise OSError(error, "Atomic request publication failed")


def _publish(update, entries, previous, raw):
    temporary = ".request-" + secrets.token_hex(16)
    fd = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
        0o600,
        dir_fd=update.fd,
    )
    identity = fs._identity(os.fstat(fd))
    try:
        with os.fdopen(fd, "wb", closefd=False) as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(fd)
        temp = fs._Entry(fd, update.fd, temporary, os.fstat(fd))
        fs._check([*entries, temp])
        if previous is None:
            _rename_no_replace(update.fd, temporary, "request.json")
        else:
            previous.check()
            os.replace(temporary, "request.json", src_dir_fd=update.fd, dst_dir_fd=update.fd)
        os.fsync(update.fd)
        fs._check(entries)
    finally:
        os.close(fd)
        try:
            info = os.stat(temporary, dir_fd=update.fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            if fs._identity(info) == identity:
                os.unlink(temporary, dir_fd=update.fd)


def submit_update(paths: Paths, channel: str = "stable") -> UpdateResult:
    """Publish once and await a protected matching-ID claim, NOT completion.

    Hold one cross-process lease through acknowledgement. On any failure leave the
    request intact: a start/fsync failure can still have queued/claimed the request.
    Only an inactive worker plus a full 30-second unclaimed timeout permits retry.
    """
    request_id = None
    try:
        validate_channel(channel)
        _managed(paths)
        with _submission_lock(paths) as (stack, update, entries):
            worker = _worker_state()
            if worker == "active":
                return UpdateResult("busy", error="Another release update is active")
            previous, pending = _existing(stack, update)
            public = read_status(paths)
            if public["phase"] not in TERMINAL:
                return UpdateResult("blocked", error=RECOVERY, request_id=public.get("request_id"))
            if (
                pending is not None
                and public.get("request_id") != pending.request_id
                and time.time() - previous.info.st_mtime < STALE_SECONDS
            ):
                return UpdateResult(
                    "busy",
                    error="Update request is awaiting acknowledgement",
                    request_id=pending.request_id,
                )
            request_id = str(uuid4())
            raw = json.dumps(
                {"format_version": 1, "request_id": request_id, "channel": channel},
                separators=(",", ":"),
            ).encode()
            parse_request(raw)
            fs._check(entries)
            # Recheck manager immediately before replacement; never replace live work.
            if _worker_state() != "inactive":
                return UpdateResult("busy", error="Another release update is active")
            _publish(update, entries, previous, raw)
            started = subprocess.run(
                ["sudo", "-n", SYSTEMCTL, "start", "--no-block", UNIT],
                capture_output=True,
                text=True,
                timeout=COMMAND_TIMEOUT_SECONDS,
                check=False,
                env={"PATH": "/usr/bin:/bin", "LANG": "C"},
            )
            if started.returncode:
                return UpdateResult("failed", error=SETUP, request_id=request_id)
            deadline = time.monotonic() + ACK_TIMEOUT
            while True:
                fs._check(entries)
                public = read_status(paths)
                if public.get("request_id") == request_id:
                    return UpdateResult("submitted", request_id=request_id)
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return UpdateResult(
                        "failed",
                        error="No matching updater acknowledgement within 30 seconds; request retained. Check the update log/service or use verified administrator repair.",
                        request_id=request_id,
                    )
                time.sleep(min(POLL_INTERVAL, remaining))
    except BlockingIOError:
        return UpdateResult("busy", error="Another update submission is in progress")
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
        return UpdateResult("failed", error=SETUP, request_id=request_id)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Submit a verified release update (unprivileged service context)"
    )
    parser.add_argument("--channel", choices=("stable", "prerelease"), default="stable")
    args = parser.parse_args(argv)
    if os.name != "posix" or os.geteuid() == 0:
        parser.exit(1, "Run the submission client as the Web UI service identity, not root.\n")
    from knxoh_paths import get_paths

    app_paths = get_paths()
    result = submit_update(
        Paths(
            app_paths.install_dir / "releases",
            app_paths.install_dir / "current",
            app_paths.config_dir,
            app_paths.data_dir,
            app_paths.backup_dir,
        ),
        args.channel,
    )
    print(json.dumps(asdict(result)))
    return 0 if result.status == "submitted" else (2 if result.status == "busy" else 1)


if __name__ == "__main__":
    raise SystemExit(main())
