"""Durable protocol-1 state; callers hold LifecycleLock for all state mutations.

Only this protected journal supplies recovery provenance. Public status and logs
are separate sanitized projections, never a source of recovery instructions.
Service control and phase ordering belong to the fixed coordinator, not this store.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import stat
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path

from . import secure_fs as fs
from .protocol import Journal, Limits, Paths, parse_object, parse_request

PHASES = frozenset(
    {
        "claimed",
        "preparing",
        "prepared",
        "quiescing",
        "snapshotted",
        "config-written",
        "activated",
        "checking",
        "committed",
        "rolling-back",
        "recovered-awaiting-start",
        "rolled-back",
        "recovery-failed",
        "recovery-failed-pre-mutation",
    }
)
TERMINAL = frozenset({"committed", "rolled-back"})
SERVICES = frozenset(
    {
        "knxohui.service",
        "knxohui-backup-cleanup.service",
        "knxohui-backup-cleanup.timer",
    }
)
STATE_BYTES = 2 * 1024 * 1024
MAX_REPLAY_IDS = 16384  # Never evict IDs; fail closed until an administrator upgrades capacity.


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _config_dir(paths):
    if paths.config_dir is None:
        raise ValueError("Missing protected CONFIG_DIR")
    config = fs._canonical(paths.config_dir)
    releases = fs._canonical(paths.releases)
    current = fs._canonical(paths.current)
    if (
        config == releases
        or config in releases.parents
        or releases in config.parents
        or config == current
        or current in config.parents
        or config in current.parents
        or current == releases
        or releases in current.parents
    ):
        raise ValueError("Config, releases, and current must be disjoint")
    _directory(config)
    _directory(releases)
    return config


def _directory(path, private=False, create=False):
    with fs._parent(path) as (stack, parent, name, chain):
        if create:
            try:
                os.mkdir(name, 0o700, dir_fd=parent)
            except FileExistsError:
                pass
            else:
                os.fsync(parent)
        entry = fs._open(stack, parent, name, {0}, os.fstat(parent).st_dev, directory=True)
        if private and stat.S_IMODE(entry.info.st_mode) != 0o700:
            raise ValueError("Recovery state directory must be private")
        fs._check([*chain, entry])


def _unlink(path):
    with fs._parent(path) as (stack, parent, name, chain):
        try:
            entry = fs._open(stack, parent, name, {0}, os.fstat(parent).st_dev)
        except FileNotFoundError:
            fs._check(chain)
            # A previous unlink may have succeeded before its directory fsync
            # failed. Retrying an absent leaf must still make absence durable.
            os.fsync(parent)
            return
        fs._check([*chain, entry])
        os.unlink(name, dir_fd=parent)
        os.fsync(parent)


class LifecycleLock:
    """One nonblocking host lock; never unlink it, including on exceptions.

    A nondefault path is for protected isolated test fixtures. Nested installer
    calls must pass ownership explicitly instead of reacquiring this lock.
    """

    def __init__(self, path: Path = Path("/run/lock/knxohui-lifecycle.lock")):
        self.path = path

    @contextmanager
    def _parent(self):
        path = fs._canonical(self.path)
        # The conventional /run/lock is 1777. Only the immediate lock
        # directory may use this exact root-owned sticky mode: sticky protects
        # the root-owned leaf against unlink/rename by other users. Every higher
        # ancestor retains secure_fs's strict nonwritable-root requirement.
        with fs._parent(path.parent) as (stack, parent, name, chain):
            before = os.stat(name, dir_fd=parent, follow_symlinks=False)
            if (
                not stat.S_ISDIR(before.st_mode)
                or before.st_uid != 0
                or (before.st_mode & 0o7022 and stat.S_IMODE(before.st_mode) != 0o1777)
            ):
                raise ValueError("Unsafe lifecycle lock directory")
            fd = os.open(
                name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent
            )
            stack.callback(os.close, fd)
            entry = fs._Entry(fd, parent, name, before)
            fs._check([*chain, entry])
            yield stack, fd, path.name, [*chain, entry]

    @contextmanager
    def acquire(self):
        import fcntl

        with self._parent() as (stack, parent, name, chain):
            try:
                fd = os.open(
                    name,
                    os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                    0o600,
                    dir_fd=parent,
                )
            except FileExistsError:
                pass
            else:
                os.close(fd)
                os.fsync(parent)
            entry = fs._open(stack, parent, name, {0}, os.fstat(parent).st_dev)
            fcntl.flock(entry.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            try:
                fs._check([*chain, entry])
                yield entry.fd
            finally:
                fcntl.flock(entry.fd, fcntl.LOCK_UN)

    @contextmanager
    def inherited(self, fd):
        """Validate a live inherited exclusive lease, not an environment boolean.

        A separate open description must conflict; flock on the inherited one
        must succeed. Together these reject an unlocked FD or somebody else's
        lock, and inode/owner checks prevent substitution. Never unlock here.
        """
        import fcntl

        with self._parent() as (stack, parent, name, chain):
            entry = fs._open(stack, parent, name, {0}, os.fstat(parent).st_dev)
            info = os.fstat(fd)
            if (
                (info.st_dev, info.st_ino) != (entry.info.st_dev, entry.info.st_ino)
                or info.st_uid != 0
                or info.st_nlink != 1
                or stat.S_IMODE(info.st_mode) != 0o600
            ):
                raise ValueError("Invalid inherited lifecycle descriptor")
            try:
                fcntl.flock(entry.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                pass
            else:
                fcntl.flock(entry.fd, fcntl.LOCK_UN)
                raise ValueError("Inherited lifecycle descriptor is not locked")
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fs._check([*chain, entry])
            yield fd


def _release(path, paths):
    if not isinstance(path, (str, Path)):
        raise ValueError("Invalid release path type")
    value = fs._canonical(path)
    if value.parent != fs._canonical(paths.releases):
        raise ValueError("Journal release outside protected releases")
    return value


def _decode_journal(value, paths):
    if set(value) != set(Journal.__dataclass_fields__):
        raise ValueError("Unknown or missing journal fields")
    parse_request(
        _json(
            {
                "format_version": value["format_version"],
                "request_id": value["request_id"],
                "channel": value["channel"],
            }
        )
    )
    if (
        not isinstance(value["phase"], str)
        or value["phase"] not in PHASES
        or value["snapshot_allowlist"] != ["config.json"]
    ):
        raise ValueError("Unknown phase or config snapshot allowlist")
    for key in ("candidate_created", "candidate_published"):
        if type(value[key]) is not bool:
            raise ValueError("Invalid candidate provenance flag")
    uid = value["candidate_uid"]
    if type(uid) is not int or not 0 <= uid < 2**32 - 1:
        raise ValueError("Invalid candidate owner")
    identity = value["candidate_identity"]
    if identity is not None and (
        not isinstance(identity, list)
        or len(identity) != 2
        or any(type(part) is not int or part < 0 for part in identity)
    ):
        raise ValueError("Invalid candidate identity")
    prior = _release(value["prior_target"], paths)
    candidate = None if value["candidate"] is None else _release(value["candidate"], paths)
    if candidate == prior or (
        value["candidate_created"] and (candidate is None or identity is None)
    ):
        raise ValueError("Inconsistent candidate provenance")
    if value["candidate_published"] and not value["candidate_created"]:
        raise ValueError("Published candidate lacks reservation")
    services = value["service_states"]
    if not isinstance(services, dict) or not set(services) <= SERVICES:
        raise ValueError("Unexpected service state")
    for service in services.values():
        if (
            not isinstance(service, dict)
            or set(service) != {"active", "enabled"}
            or any(type(flag) is not bool for flag in service.values())
        ):
            raise ValueError("Invalid service state flags")
    return Journal(
        **{
            **value,
            "candidate": candidate,
            "prior_target": prior,
            "candidate_identity": None if identity is None else tuple(identity),
            "snapshot_allowlist": ("config.json",),
        }
    )


def _journal_dict(journal):
    value = asdict(journal)
    value["candidate"] = None if journal.candidate is None else str(journal.candidate)
    value["prior_target"] = str(journal.prior_target)
    # JSON roundtrip converts tuple fields to their wire representation.
    return parse_object(_json(value), STATE_BYTES)


def _decode_record(value, paths):
    """The original exact journal + replay-ledger decoder, shared by archives."""
    value = dict(value)
    ids = value.pop("seen_request_ids", None)
    if not isinstance(ids, list) or not 1 <= len(ids) <= MAX_REPLAY_IDS:
        raise ValueError("Invalid replay ledger")
    for request_id in ids:
        parse_request(_json({"format_version": 1, "request_id": request_id, "channel": "stable"}))
    if len(set(ids)) != len(ids):
        raise ValueError("Duplicate replay IDs")
    journal = _decode_journal(value, paths)
    if journal.request_id != ids[-1]:
        raise ValueError("Journal does not match replay ledger")
    return journal, ids


class StateStore:
    def __init__(self, paths: Paths):
        self.paths = paths
        config = _config_dir(paths)
        self.root = config / ".updater-state"
        _directory(self.root, private=True, create=True)
        self.journal_path = self.root / "journal.json"

    def _read(self):
        _config_dir(self.paths)
        _directory(self.root, private=True)
        try:
            value = parse_object(fs.read_regular(self.journal_path, STATE_BYTES), STATE_BYTES)
        except FileNotFoundError:
            return None, []
        if "admin_history_version" not in value:
            return _decode_record(value, self.paths)
        # Separate, exact administrator checkpoint schema, NOT a relaxed Journal.
        # Older coordinators reject it instead of treating an absent journal as
        # a fresh empty replay ledger if bootstrap is interrupted before upgrade.
        if (
            set(value) != {"admin_history_version", "request_id", "archive_sha256"}
            or type(value["admin_history_version"]) is not int
            or value["admin_history_version"] != 1
            or not _digest(value["archive_sha256"])
        ):
            raise ValueError("Unknown administrator history checkpoint")
        request = parse_request(
            _json({"format_version": 1, "request_id": value["request_id"], "channel": "stable"})
        )
        raw = fs.read_regular(self.root / ("terminal-" + request.request_id + ".json"), STATE_BYTES)
        if hashlib.sha256(raw).hexdigest() != value["archive_sha256"]:
            raise ValueError("Administrator history archive digest mismatch")
        journal, ids = _decode_record(parse_object(raw, STATE_BYTES), self.paths)
        if journal.phase not in TERMINAL or journal.request_id != request.request_id:
            raise ValueError("Administrator history is not terminal")
        return None, ids

    def load(self) -> Journal | None:
        return self._read()[0]

    def archive_terminal_for_admin(self) -> bool:
        """Caller holds LifecycleLock: durably detach terminal recovery authority.

        Preserve exact journal bytes, snapshots and ALL replay IDs. An atomic
        checkpoint replaces (never unlinks) journal.json only after the archive
        is durable. Retrying a visible checkpoint fsyncs its parent. Future or
        corrupt records never become archives; an active transaction blocks.
        """
        journal, _ = self._read()
        for name in (".updater-maintenance.json", ".updater-startup-gate.json"):
            try:
                fs.read_regular(self.paths.config_dir / name, 4096)
            except FileNotFoundError:
                continue
            raise ValueError("Reconcile updater gate/maintenance before administrator transition")
        if journal is None:
            with fs._parent(self.journal_path) as (_, parent, _, chain):
                fs._check(chain)
                os.fsync(parent)
            return False
        if journal.phase not in TERMINAL:
            raise ValueError("Recover active transaction before administrator transition")
        target = journal.candidate if journal.phase == "committed" else journal.prior_target
        if _current_target(self.paths)[0] != target or not check_start_allowed(
            self.paths, "cleanup"
        ):
            raise ValueError("Terminal journal/current mismatch or incomplete pair")
        raw = fs.read_regular(self.journal_path, STATE_BYTES)
        archive = self.root / ("terminal-" + journal.request_id + ".json")
        try:
            previous = fs.read_regular(archive, STATE_BYTES)
        except FileNotFoundError:
            fs.atomic_write(archive, raw, 0, 0, 0o600)
        else:
            if previous != raw:
                raise ValueError("Conflicting administrator terminal archive")
        fs.atomic_write(
            self.journal_path,
            _json(
                {
                    "admin_history_version": 1,
                    "request_id": journal.request_id,
                    "archive_sha256": hashlib.sha256(raw).hexdigest(),
                }
            ),
            0,
            0,
            0o600,
        )
        return True

    def save(self, journal: Journal) -> None:
        value = _journal_dict(journal)
        _decode_journal(value, self.paths)
        previous, ids = self._read()
        if previous is None or previous.request_id != journal.request_id:
            if previous is not None and previous.phase not in TERMINAL:
                raise ValueError("Recover active transaction first")
            if (
                journal.phase != "claimed"
                or journal.request_id in ids
                or len(ids) >= MAX_REPLAY_IDS
            ):
                raise ValueError("Stale/replayed request or full replay ledger")
            ids.append(journal.request_id)
        else:
            if previous.phase in TERMINAL and journal != previous:
                raise ValueError("Terminal transaction is immutable")
            for key in ("prior_target", "channel", "snapshot_allowlist", "candidate_uid"):
                if getattr(previous, key) != getattr(journal, key):
                    raise ValueError("Transaction provenance changed")
            for key in ("candidate", "candidate_identity"):
                if getattr(previous, key) is not None and getattr(previous, key) != getattr(
                    journal, key
                ):
                    raise ValueError("Candidate provenance changed")
            if (
                previous.candidate_created
                and not journal.candidate_created
                or previous.candidate_published
                and not journal.candidate_published
                or previous.service_states
                and previous.service_states != journal.service_states
            ):
                raise ValueError("Sticky transaction provenance changed")
        fs.atomic_write(self.journal_path, _json({**value, "seen_request_ids": ids}), 0, 0, 0o600)

    def _snapshot_path(self):
        journal = self.load()
        if journal is None:
            raise ValueError("No protected transaction")
        return journal, self.root / ("snapshot-" + journal.request_id + ".json")

    def snapshot_config(self) -> None:
        journal, destination = self._snapshot_path()
        # Never replace original evidence with already migrated bytes.
        try:
            fs.read_regular(destination, STATE_BYTES)
        except FileNotFoundError:
            pass
        else:
            raise ValueError("Snapshot already exists")
        path = self.paths.config_dir / "config.json"
        with fs._parent(path) as (stack, parent, name, chain):
            try:
                entry = fs._open(stack, parent, name, {0}, os.fstat(parent).st_dev)
            except FileNotFoundError:
                snapshot = {"present": False}
            else:
                raw = fs.read_regular(path, Limits.CONFIG_BYTES)
                fs._check([*chain, entry])
                after = os.fstat(entry.fd)
                if (entry.info.st_size, entry.info.st_mtime_ns, entry.info.st_ctime_ns) != (
                    after.st_size,
                    after.st_mtime_ns,
                    after.st_ctime_ns,
                ):
                    raise ValueError("Config changed during snapshot")
                snapshot = {
                    "present": True,
                    "bytes": base64.b64encode(raw).decode("ascii"),
                    "uid": entry.info.st_uid,
                    "gid": entry.info.st_gid,
                    "mode": stat.S_IMODE(entry.info.st_mode),
                }
            fs._check(chain)
        fs.atomic_write(
            destination,
            _json(
                {
                    "format_version": 1,
                    "request_id": journal.request_id,
                    "files": {"config.json": snapshot},
                }
            ),
            0,
            0,
            0o600,
        )

    def restore_config(self) -> None:
        journal, source = self._snapshot_path()
        value = parse_object(fs.read_regular(source, STATE_BYTES), STATE_BYTES)
        if (
            set(value) != {"format_version", "request_id", "files"}
            or type(value["format_version"]) is not int
            or value["format_version"] != 1
            or value["request_id"] != journal.request_id
            or not isinstance(value["files"], dict)
            or set(value["files"]) != {"config.json"}
        ):
            raise ValueError("Invalid config snapshot")
        snapshot = value["files"]["config.json"]
        if not isinstance(snapshot, dict) or type(snapshot.get("present")) is not bool:
            raise ValueError("Invalid snapshot presence")
        path = self.paths.config_dir / "config.json"
        if not snapshot["present"]:
            if set(snapshot) != {"present"}:
                raise ValueError("Invalid absent snapshot")
            write_gate(self.paths, "deny", None, None)
            _unlink(path)
            return
        if set(snapshot) != {"present", "bytes", "uid", "gid", "mode"}:
            raise ValueError("Invalid snapshot metadata")
        if (
            type(snapshot["uid"]) is not int
            or snapshot["uid"] != 0
            or type(snapshot["gid"]) is not int
            or not 0 <= snapshot["gid"] < 2**32 - 1
            or type(snapshot["mode"]) is not int
            or snapshot["mode"] < 0
            or snapshot["mode"] & ~0o755
            or not isinstance(snapshot["bytes"], str)
        ):
            raise ValueError("Unsafe snapshot metadata")
        raw = base64.b64decode(snapshot["bytes"], validate=True)
        if len(raw) > Limits.CONFIG_BYTES:
            raise ValueError("Oversized snapshot")
        write_gate(self.paths, "deny", None, None)
        fs.atomic_write(path, raw, snapshot["uid"], snapshot["gid"], snapshot["mode"])

    def publish_status(self, phase: str, message: str, request_id: str | None = None) -> None:
        """Publish coordinator-authored text only; NEVER pass child output/secrets.

        No free-form child-log append interface is provided. The bounded log is a
        last-status projection, so private diagnostics cannot leak by default.
        """
        config = _config_dir(self.paths)
        if (
            phase not in PHASES
            or not isinstance(message, str)
            or not message
            or len(message.encode()) > 1024
            or any(ord(c) < 32 or ord(c) == 127 for c in message)
        ):
            raise ValueError("Invalid public status")
        identity = {}
        if request_id is not None:
            parse_request(
                _json({"format_version": 1, "request_id": request_id, "channel": "stable"})
            )
            identity["request_id"] = request_id
        fs.atomic_write(
            config / ".updater-status.json",
            _json(
                {
                    "format_version": 1,
                    "phase": phase,
                    "message": message,
                    **identity,
                }
            ),
            0,
            0,
            0o644,
        )
        fs.atomic_write(
            config / ".updater-log.txt", (phase + ": " + message + "\n").encode(), 0, 0, 0o644
        )


def _current_target(paths):
    with fs._parent(paths.current) as (_, parent, name, chain):
        before = os.stat(name, dir_fd=parent, follow_symlinks=False)
        if not stat.S_ISLNK(before.st_mode) or before.st_uid != 0:
            raise ValueError("Unsafe current link")
        target = os.readlink(name, dir_fd=parent)
        resolved = Path(os.path.normpath(os.path.join(str(paths.current.parent), target)))
        _release(resolved, paths)
        _directory(resolved)
        fs._check(chain)
        after = os.stat(name, dir_fd=parent, follow_symlinks=False)
        if fs._metadata(before) != fs._metadata(after) or target != os.readlink(
            name, dir_fd=parent
        ):
            raise ValueError("Current changed during guard")
        return resolved, (before.st_dev, before.st_ino, target)


def write_gate(paths: Paths, mode: str, target: Path | None, config_digest: str | None) -> None:
    config = _config_dir(paths)
    destination = config / ".updater-startup-gate.json"
    if mode not in ("deny", "permit", "clear"):
        raise ValueError("Unknown gate mode")
    if mode != "permit":
        if target is not None or config_digest is not None:
            raise ValueError("Unexpected deny/clear target")
    else:
        _release(target, paths)
        if not _digest(config_digest):
            raise ValueError("Invalid config digest")
    if mode == "clear":
        _unlink(destination)
    else:
        fs.atomic_write(
            destination,
            _json(
                {
                    "format_version": 1,
                    "mode": mode,
                    "target": None if target is None else str(target),
                    "config_digest": config_digest,
                }
            ),
            0,
            0,
            0o644,
        )


def _digest(value):
    return (
        isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)
    )


def check_start_allowed(paths: Paths, role: str) -> bool:
    """Unprivileged, lock-free check. Never read private journal/snapshot state."""
    try:
        if role not in ("ui", "cleanup"):
            return False
        config = _config_dir(paths)
        current, identity = _current_target(paths)
        # Administrator setup's root-authored incomplete marker must also gate
        # same-boot restarts after recovery already reached active (exited).
        for marker in (
            current / ".install-incomplete",
            paths.releases.parent / ".install-incomplete",
            paths.releases.parent / ".installer-incomplete",
            config / ".installer-incomplete",
        ):
            with fs._parent(marker) as (_, parent, name, chain):
                try:
                    os.stat(name, dir_fd=parent, follow_symlinks=False)
                except FileNotFoundError:
                    fs._check(chain)
                else:
                    return False
        gate = config / ".updater-startup-gate.json"
        try:
            raw = fs.read_regular(gate, 4096)
        except FileNotFoundError:
            # Only the leaf may be absent, never an unsafe/missing parent.
            _directory(config)
            return _current_target(paths) == (current, identity)
        with fs._parent(gate) as (stack, parent, name, chain):
            entry = fs._open(stack, parent, name, {0}, os.fstat(parent).st_dev)
            if entry.info.st_mode & 0o444 != 0o444:
                return False
            fs._check([*chain, entry])
        value = parse_object(raw, 4096)
        if (
            set(value) != {"format_version", "mode", "target", "config_digest"}
            or type(value["format_version"]) is not int
            or value["format_version"] != 1
            or value["mode"] != "permit"
            or role != "ui"
            or not _digest(value["config_digest"])
            or _release(value["target"], paths) != current
        ):
            return False
        digest = hashlib.sha256(
            fs.read_regular(config / "config.json", Limits.CONFIG_BYTES)
        ).hexdigest()
        # Detect observed link/gate changes while hashing. Configuration is only
        # writable by the coordinator, which writes deny before each mutation.
        return (
            digest == value["config_digest"]
            and _current_target(paths) == (current, identity)
            and fs.read_regular(gate, 4096) == raw
        )
    except (OSError, ValueError, TypeError, KeyError, NotImplementedError):
        return False
