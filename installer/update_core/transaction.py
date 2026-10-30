"""Fixed privileged coordinator. No application imports or candidate execution.

Journal phases describe INTENT (an operation may or may not have happened).
Repeated phase saves precede each effect, including rollback and finalization.
Only committed/rolled-back are terminal; recovery never infers intent from public
status, child markers, or the service-owned request directory.
"""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import logging
import os
import queue
import secrets
import shlex
import stat
import sys
import threading
import time
import urllib.request
from contextlib import contextmanager
from dataclasses import asdict, dataclass, replace
from pathlib import Path

from . import artifacts, maintenance
from . import secure_fs as fs
from .protocol import Journal, Limits, Paths, parse_object, parse_request, validate_config_copy
from .state import (
    SERVICES,
    TERMINAL,
    LifecycleLock,
    StateStore,
    _current_target,
    _directory,
    _unlink,
    check_start_allowed,
    write_gate,
)
from .systemd import STAGES, SystemdAdapter, _path

UI = "knxohui.service"
CLEANUP = ("knxohui-backup-cleanup.service", "knxohui-backup-cleanup.timer")
MAY_WRITE_CONFIG = frozenset(
    {
        "config-written",
        "activated",
        "checking",
        "rolling-back",
        "recovery-failed",
        "recovered-awaiting-start",
    }
)
PATH_KEYS = ("KNXOH_INSTALL_DIR", "KNXOH_CONFIG_DIR", "KNXOH_DATA_DIR", "KNXOH_BACKUP_DIR")
ADMIN = (
    "Recovery evidence retained; run installed offline recovery or verified administrator bootstrap"
)


@dataclass(frozen=True)
class UpdateResult:
    status: str
    version: str | None = None
    error: str | None = None
    rollback_status: str | None = None
    request_id: str | None = None


class CoordinatorError(ValueError):
    """Fixed coordinator-authored guidance; never constructed from child output."""


def _diagnostic(error):
    return str(error) if isinstance(error, CoordinatorError) else type(error).__name__


def nofile_limits():
    import resource

    return resource.getrlimit(resource.RLIMIT_NOFILE)


def available_bytes(path):
    info = os.statvfs(path)
    return info.f_bavail * info.f_frsize


def load_paths(path=Path("/etc/knx_to_openhab/paths.env")) -> Paths:
    """Parse the protected canonical contract as data, never source/evaluate it."""
    values = {}
    for line in fs.read_regular(path, 16384).decode("utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        name, separator, raw = line.partition("=")
        if not separator or name not in PATH_KEYS or name in values:
            raise ValueError("Invalid canonical paths contract; use verified bootstrap")
        tokens = shlex.split(raw, comments=False, posix=True)
        if len(tokens) != 1:
            raise ValueError("Invalid canonical path value")
        values[name] = Path(tokens[0])
        _path(values[name])
        fs._canonical(values[name])
    if set(values) != set(PATH_KEYS):
        raise ValueError("Incomplete canonical paths contract; use verified bootstrap")
    base, config, data, backups = (values[key] for key in PATH_KEYS)
    return Paths(base / "releases", base / "current", config, data, backups)


def reject_credentials(config):
    """Never give candidate code embedded passwords, hashes, keys or tokens."""
    forbidden = {
        "password",
        "password_hash",
        "password_b64",
        "secret",
        "session_secret",
        "token",
        "api_key",
        "private_key",
        "credentials",
    }

    def visit(value):
        if isinstance(value, dict):
            for key, child in value.items():
                normalized = key.lower().replace("-", "_")
                if normalized in forbidden or set(normalized.split("_")) & {
                    "password",
                    "secret",
                    "token",
                    "credentials",
                }:
                    raise CoordinatorError(
                        "Embedded credentials require administrator externalization"
                    )
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(config)


def health_url(config):
    # Match the direct Gunicorn listener, not a reverse proxy's public scheme.
    # Gunicorn reads only bind_host/port; unrelated config keys stay uninterpreted.
    host = config.get("bind_host", "127.0.0.1")
    port = config.get("port", 8085)
    if not isinstance(host, str) or type(port) is not int or not 1 <= port <= 65535:
        raise ValueError("Invalid configured local HTTP endpoint")
    host = host.strip("[]")
    if host == "localhost":
        host = "127.0.0.1"
    address = ipaddress.ip_address(host)
    if address.is_unspecified:
        host = "::1" if address.version == 6 else "127.0.0.1"
    if ":" in host:
        host = "[" + host + "]"
    return f"http://{host}:{port}/api/health"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError("Readiness redirects are not allowed")


def fetch_health(url, timeout):
    # Do not inherit proxy settings or follow health redirects off the direct
    # configured HTTP listener. Public reverse-proxy HTTPS is not readiness.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
    with opener.open(url, timeout=timeout) as response:
        if response.status != 200:
            raise ValueError("HTTP readiness failed")
        return parse_object(response.read(4097), 4096)


class ReleaseUpdater:
    def __init__(
        self,
        paths: Paths,
        systemd: SystemdAdapter,
        limits: Limits,
        *,
        lock_path=Path("/run/lock/knxohui-lifecycle.lock"),
        workspace_root=Path("/var/lib/knxohupdate-preparation"),
        worker_uid=None,
        worker_gid=None,
        service_uid=None,
        http=fetch_health,
        readiness_timeout=60.0,
        drain_timeout=120.0,
    ):
        self.paths, self.systemd, self.limits = paths, systemd, limits
        self.lock_path, self.workspace_root = lock_path, workspace_root
        self.worker_uid, self.worker_gid, self.service_uid = worker_uid, worker_gid, service_uid
        self.http = http
        if not 0 < readiness_timeout <= 60 or not 0 <= drain_timeout <= 120:
            raise ValueError("Invalid coordinator time budget")
        self.readiness_timeout, self.drain_timeout = readiness_timeout, drain_timeout
        self.store = None
        self.journal = None

    def _boundary(self, label):
        """Non-sensitive diagnostics at durable intent/effect boundaries."""
        logging.getLogger(__name__).debug("Release transaction boundary: %s", label)

    def _intent(self, phase=None, **changes):
        intended = replace(self.journal, phase=phase or self.journal.phase, **changes)
        self.store.save(intended)
        self.journal = intended
        self._boundary("intent:" + self.journal.phase)

    def _effect(self, label, function, *args):
        self._intent()
        function(*args)
        self._boundary("effect:" + label)

    def _identities(self):
        import pwd

        if self.worker_uid is None or self.worker_gid is None:
            worker = pwd.getpwnam("knxohupdate")
            self.worker_uid, self.worker_gid = worker.pw_uid, worker.pw_gid
            if worker.pw_uid == 0 or worker.pw_shell not in (
                "/usr/sbin/nologin",
                "/sbin/nologin",
                "/bin/false",
            ):
                raise ValueError("Unsafe preparation identity; use verified bootstrap")
            groups = set(os.getgrouplist(worker.pw_name, worker.pw_gid))
            for name in ("knxohui", "openhab", "sudo", "wheel"):
                import grp

                try:
                    gid = grp.getgrnam(name).gr_gid
                except KeyError:
                    continue
                if gid in groups:
                    raise ValueError("Preparation identity has forbidden group membership")
        if self.service_uid is None:
            self.service_uid = pwd.getpwnam("knxohui").pw_uid
        if 0 in (self.worker_uid, self.service_uid) or self.worker_uid == self.service_uid:
            raise ValueError("Distinct unprivileged identities required")

    def _layout(self, preparation=False):
        paths = self.paths
        if any(path is None for path in (paths.config_dir, paths.data_dir, paths.backup_dir)):
            raise ValueError("Legacy installation; use verified administrator bootstrap")
        directories = [
            paths.releases.parent,
            paths.config_dir,
            paths.data_dir,
            paths.backup_dir,
            self.workspace_root,
        ]
        for path in [*directories, paths.releases, paths.current]:
            _path(path)
            fs._canonical(path)
        for index, left in enumerate(directories):
            for right in directories[index + 1 :]:
                if left == right or left in right.parents or right in left.parents:
                    raise ValueError("Canonical installation paths overlap")
        _directory(paths.releases)
        _directory(paths.config_dir)
        _directory(self.workspace_root)
        for directory in (paths.data_dir, paths.backup_dir):
            with fs._parent(directory) as (stack, parent, name, chain):
                entry = fs._open(stack, parent, name, {self.service_uid}, None, directory=True)
                fs._check([*chain, entry])
        for marker in (
            paths.config_dir / ".installer-incomplete",
            paths.releases.parent / ".installer-incomplete",
        ):
            with fs._parent(marker) as (_, parent, name, chain):
                try:
                    os.stat(name, dir_fd=parent, follow_symlinks=False)
                except FileNotFoundError:
                    pass
                else:
                    raise ValueError("Installer incomplete; use verified bootstrap")
                fs._check(chain)
        current, _ = _current_target(paths)
        for marker in (
            current / ".install-incomplete",
            paths.releases.parent / ".install-incomplete",
        ):
            with fs._parent(marker) as (_, parent, name, chain):
                try:
                    os.stat(name, dir_fd=parent, follow_symlinks=False)
                except FileNotFoundError:
                    fs._check(chain)
                else:
                    raise ValueError("Installer incomplete; use verified bootstrap")
        if preparation:
            soft, hard = nofile_limits()
            if any(
                value != -1 and value < self.limits.COORDINATOR_NOFILE for value in (soft, hard)
            ):
                raise CoordinatorError(
                    "Coordinator needs soft/hard LimitNOFILE=32768; use verified bootstrap"
                )
            budget = 2 * self.limits.ARCHIVE_BYTES + 2 * self.limits.TREE_BYTES
            for path in (paths.releases, self.workspace_root, paths.config_dir):
                if available_bytes(path) < budget:
                    raise CoordinatorError(
                        "Insufficient free space for bounded release preparation and recovery"
                    )
            secret_path = paths.config_dir / "secrets.env"
            raw_secret = fs.read_regular(secret_path, self.limits.CONFIG_BYTES)
            with fs._parent(secret_path) as (stack, parent, name, chain):
                entry = fs._open(stack, parent, name, {0}, os.fstat(parent).st_dev)
                if stat.S_IMODE(entry.info.st_mode) not in (0o600, 0o640):
                    raise CoordinatorError(
                        "External credentials must have restricted 0600/0640 permissions"
                    )
                fs._check([*chain, entry])
            if any(
                line.partition(b"=")[0].strip() == b"KNXOH_UI_PASSWORD_B64"
                for line in raw_secret.splitlines()
            ):
                raise CoordinatorError(
                    "Legacy plaintext credentials require verified administrator bootstrap"
                )
            original = self._config()
            reject_credentials(original)
            health_url(original)
            if maintenance.maintenance_requested(paths):
                raise ValueError("Unreconciled maintenance intent; recover first")
            if not check_start_allowed(paths, "cleanup"):
                raise ValueError("Unreconciled startup gate; recover first")
            # Validate the provisioned, never-replaced lease before preparing code.
            with maintenance._lease_fd(paths):
                pass
            try:
                self._frozen(current)
            except (OSError, ValueError) as error:
                raise CoordinatorError(fs.EXISTING_RELEASE_GUIDANCE) from error
            self._version(current)
            for hidden in (Path("/root"), Path("/home"), Path("/tmp")):
                if self.workspace_root == hidden or hidden in self.workspace_root.parents:
                    raise ValueError("Preparation workspace is hidden by the child sandbox")
            # The child gets no supplementary groups. Every protected parent
            # must permit traversal with exactly its trusted UID/GID.
            for parent in (*reversed(self.workspace_root.parents[:-1]), self.workspace_root):
                info = parent.stat()
                bit = (
                    0o100
                    if info.st_uid == self.worker_uid
                    else (0o010 if info.st_gid == self.worker_gid else 0o001)
                )
                if not info.st_mode & bit:
                    raise ValueError("Preparation workspace is not worker-traversable")

    def _config(self):
        return parse_object(
            fs.read_regular(self.paths.config_dir / "config.json", self.limits.CONFIG_BYTES),
            self.limits.CONFIG_BYTES,
        )

    def _claim(self):
        """Narrow exception for ONE service-owned input; never root read_regular."""
        with fs._parent(self.paths.data_dir) as (stack, parent, name, chain):
            data = fs._open(stack, parent, name, {self.service_uid}, None, directory=True)
            update = fs._open(
                stack, data.fd, "update", {self.service_uid}, data.info.st_dev, directory=True
            )
            entry = fs._open(stack, update.fd, "request.json", {self.service_uid}, data.info.st_dev)
            raw = artifacts._read_entry(entry, self.limits.REQUEST_BYTES)
            fs._check([*chain, data, update, entry])
            return parse_request(raw)

    def _stop_children(self):
        self.systemd.stop_children(self.journal.request_id)
        if not set(STAGES) <= self.systemd.stopped:
            raise ValueError("Adapter did not confirm all child cgroups stopped")

    def _stage(self, stage, values, candidate=None, inputs=None):
        self._stop_children()
        root = self.workspace_root / self.journal.request_id
        _directory(root, create=True)
        # Only the preparation identity may traverse/read copied settings. These
        # files are not public status, even after embedded credentials are refused.
        with fs._parent(root) as (stack, parent, name, chain):
            entry = fs._open(stack, parent, name, {0}, os.fstat(parent).st_dev, directory=True)
            os.fchown(entry.fd, 0, self.worker_gid)
            os.fchmod(entry.fd, 0o750)
            os.fsync(entry.fd)
            fs._check(chain)
        workspace = root / stage
        with fs._parent(workspace) as (_, parent, name, chain):
            os.mkdir(name, 0o750, dir_fd=parent)  # never resume a partial stage
            fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            try:
                os.fchown(fd, 0, self.worker_gid)
                os.fchmod(fd, 0o750)
                os.fsync(fd)
            finally:
                os.close(fd)
            os.fsync(parent)
            fs._check(chain)
        fs.atomic_write(workspace / "input.json", _json(values), 0, self.worker_gid, 0o440)
        for name, raw in (inputs or {}).items():
            if name not in ("verified.tar.gz", "config-input.json"):
                raise ValueError("Unknown workspace input")
            fs.atomic_write(workspace / name, raw, 0, self.worker_gid, 0o440)
        with fs._parent(workspace / "output") as (_, parent, name, chain):
            os.mkdir(name, 0o700, dir_fd=parent)
            fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            try:
                os.fchown(fd, self.worker_uid, self.worker_gid)
                os.fsync(fd)
            finally:
                os.close(fd)
            os.fsync(parent)
            fs._check(chain)
        try:
            self.systemd.run_child(stage, self.paths, workspace, candidate)
        finally:
            self._stop_children()
        self._boundary("effect:child-" + stage)
        return workspace / "output"

    def _ingest(self, output, name, limit):
        self._stop_children()
        return artifacts.ingest_child_file(
            output, name, limit, self.worker_uid, stopped=set(STAGES) <= self.systemd.stopped
        )

    def _reserve(self, version):
        candidate = self.paths.releases / version
        with fs._parent(candidate) as (_, parent, name, chain):
            try:
                os.stat(name, dir_fd=parent, follow_symlinks=False)
            except FileNotFoundError:
                fs._check(chain)
            else:
                raise FileExistsError("Release already exists; never reuse a partial environment")
        self._intent(candidate=candidate)
        with fs._parent(candidate) as (_, parent, name, chain):
            os.mkdir(name, 0o700, dir_fd=parent)
            os.fsync(parent)
            fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            try:
                identity = fs._identity(os.fstat(fd))
                self._intent(candidate_identity=identity, candidate_created=True)
                # Journal identity is durable BEFORE the child gains ownership.
                os.fchown(fd, self.worker_uid, self.worker_gid)
                os.fsync(fd)
                fs._check(chain)
            finally:
                os.close(fd)
        self._boundary("effect:reserve")
        return candidate

    def _prepare(self, request, current_version):
        self._intent("preparing")
        output = self._stage("metadata", {"channel": request.channel})
        raw = self._ingest(output, "metadata.json", self.limits.METADATA_BYTES)
        # parse_object's duplicate/constant checks apply to nested listing entries too.
        metadata = parse_object(b'{"metadata":' + raw + b"}", self.limits.METADATA_BYTES + 32)[
            "metadata"
        ]
        release = artifacts.select_release(metadata, request.channel, current_version)
        if release is None:
            return None, None
        output = self._stage("download", {"release": asdict(release)})
        archive = self._ingest(output, "archive.tar.gz", self.limits.ARCHIVE_BYTES)
        checksum = self._ingest(output, "archive.sha256", self.limits.CHECKSUM_BYTES)
        protected = self.store.root / ("archive-" + request.request_id + ".tar.gz")
        fs.atomic_write(protected, archive, 0, 0, 0o400)
        artifacts.verify_archive(protected, checksum, release)
        candidate = self._reserve(release.version)
        self._stage(
            "extract",
            {"release": asdict(release)},
            candidate,
            {"verified.tar.gz": fs.read_regular(protected, self.limits.ARCHIVE_BYTES)},
        )
        self._stop_children()
        self._validate_release_tree(candidate, release, self.worker_uid)
        self._stage("dependencies", {}, candidate)
        self._stop_children()
        fs.freeze_tree(candidate, self.worker_uid)
        contract = self._validate_release_tree(candidate, release, 0)
        self._version(candidate)
        self._intent("prepared")
        return release, contract

    def _validate_release_tree(self, candidate, release, uid):
        try:
            return artifacts.validate_extracted_tree(candidate, release, expected_uid=uid)
        except (ValueError, OSError) as error:
            raise CoordinatorError(
                "Release tree or compatibility contract validation failed"
            ) from error

    def _service(self, action, name):
        self._effect("service-" + action + "-" + name, self.systemd.service, action, name)

    def _stop_writers(self):
        # Timer first so it cannot enqueue another cleanup after the service stop.
        for name in (CLEANUP[1], CLEANUP[0], UI):
            self._service("stop", name)

    def _capture(self):
        states = self.systemd.capture_services()
        if set(states.active) != SERVICES or set(states.enabled) != SERVICES:
            raise ValueError("Incomplete prior unit state mapping")
        self._intent(
            service_states={
                name: {"active": states.active[name], "enabled": states.enabled[name]}
                for name in SERVICES
            }
        )

    def _gate(self, mode, target=None):
        digest = None
        if mode == "permit":
            self._stop_children()
            self._validate_target(target)
            digest = hashlib.sha256(
                fs.read_regular(self.paths.config_dir / "config.json", self.limits.CONFIG_BYTES)
            ).hexdigest()
        self._effect("gate-" + mode, write_gate, self.paths, mode, target, digest)

    def _validate_target(self, target):
        if target == self.journal.candidate:
            with fs._parent(target) as (stack, parent, name, chain):
                entries = fs._tree(stack, parent, name, {0})
                if fs._identity(entries[-1].info) != self.journal.candidate_identity:
                    raise ValueError("Candidate identity mismatch")
                fs._check([*chain, *entries])
        elif target == self.journal.prior_target:
            self._frozen(target)
            self._version(target)
        else:
            raise ValueError("Unrelated activation target")

    def _frozen(self, target):
        with fs._parent(target) as (stack, parent, name, chain):
            entries = fs._tree(stack, parent, name, {0})
            fs._check([*chain, *entries])

    def _version(self, target):
        version = fs.read_regular(target / "VERSION", 256).decode("ascii").strip()
        artifacts._precedence(version)
        if version != target.name:
            raise ValueError("Release directory and VERSION disagree")
        return version

    def _switch(self, target):
        self._validate_target(target)
        current, _ = _current_target(self.paths)
        if current not in (self.journal.prior_target, self.journal.candidate):
            raise ValueError("Current/journal mismatch; administrator intervention required")
        with fs._parent(self.paths.current) as (_, parent, name, chain):
            temporary = ".updater-link-" + secrets.token_hex(16)
            os.symlink(str(target), temporary, dir_fd=parent)
            try:
                fs._check(chain)
                if _current_target(self.paths)[0] != current:
                    raise ValueError("Current changed during activation")
                os.replace(temporary, name, src_dir_fd=parent, dst_dir_fd=parent)
                os.fsync(parent)
            finally:
                try:
                    os.unlink(temporary, dir_fd=parent)
                except FileNotFoundError:
                    pass

    def _ready(self, version):
        deadline = time.monotonic() + self.readiness_timeout
        url = health_url(self._config())
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("Expected-version notify/HTTP readiness timed out")
            try:
                if self.systemd.notify_ready(
                    timeout=min(remaining, self.limits.HTTP_TIMEOUT_SECONDS)
                ):
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError("Notify exceeded readiness deadline")
                    response = self._bounded_http(
                        url, min(remaining, self.limits.HTTP_TIMEOUT_SECONDS)
                    )
                    if response == {"status": "ready", "version": version}:
                        return
            except (OSError, ValueError, TimeoutError):
                pass
            time.sleep(min(0.05, max(0, deadline - time.monotonic())))

    def _bounded_http(self, url, timeout):
        # urllib socket timeouts alone are idle timeouts: trickled headers/body
        # can otherwise exceed the coordinator's absolute readiness deadline.
        # This daemon performs read-only HTTP, never service/filesystem mutation;
        # timed-out results are discarded and cannot later commit the update.
        result = queue.Queue(maxsize=1)

        def fetch():
            try:
                result.put((True, self.http(url, timeout)))
            except Exception as error:
                result.put((False, error))

        threading.Thread(target=fetch, daemon=True, name="update-readiness").start()
        try:
            success, value = result.get(timeout=timeout)
        except queue.Empty as error:
            raise TimeoutError("HTTP readiness exceeded remaining deadline") from error
        if not success:
            raise value
        return value

    def _restore_units(self, include_ui=False, start=True):
        # UI Wants=cleanup.timer: restore UI FIRST so restoring cleanup last
        # wins over dependency activation, including originally inactive timers.
        names = ([UI] if include_ui else []) + list(CLEANUP)
        for name in names:
            if name not in self.journal.service_states:
                continue
            state = self.journal.service_states[name]
            self._service("enable" if state["enabled"] else "disable", name)
            if start or not state["active"]:
                self._service("start" if state["active"] else "stop", name)

    def _clear_maintenance(self):
        if maintenance.maintenance_requested(self.paths):
            self._effect(
                "maintenance-clear", _unlink, self.paths.config_dir / maintenance.INTENT_NAME
            )

    @contextmanager
    def _recovery_lease(self):
        """Drain behind durable recovery intent, including a crashed owner's intent."""
        import fcntl

        self._effect(
            "maintenance-request",
            fs.atomic_write,
            self.paths.config_dir / maintenance.INTENT_NAME,
            b'{"maintenance":true}',
            0,
            0,
            0o644,
        )
        with maintenance._lease_fd(self.paths) as fd:
            deadline = time.monotonic() + self.drain_timeout
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise TimeoutError("Recovery could not drain mutation leases")
                    time.sleep(min(0.05, max(0, deadline - time.monotonic())))
            yield

    def _remove_candidate(self):
        self._stop_children()
        journal = self.journal
        if journal.candidate is None or journal.candidate_published:
            return
        with fs._parent(journal.candidate) as (_, parent, name, chain):
            try:
                os.stat(name, dir_fd=parent, follow_symlinks=False)
            except FileNotFoundError:
                fs._check(chain)
                return
        if not journal.candidate_created:
            raise ValueError("Candidate exists without durable reservation identity")
        self._effect("remove-candidate", fs.remove_candidate, self.paths, journal)

    def _coherent_prior(self, mutated, stop_writers=True):
        self._stop_children()
        current, _ = _current_target(self.paths)
        if current not in (self.journal.prior_target, self.journal.candidate):
            raise ValueError("Current/journal mismatch")
        self._validate_target(self.journal.prior_target)
        if not mutated and current != self.journal.prior_target:
            raise ValueError("Unexpected publication before activation intent")
        self._gate("deny")
        if stop_writers:
            self._stop_writers()
        if mutated:
            self._intent("rolling-back")
            self._effect("restore-config", self.store.restore_config)
            self._effect("restore-link", self._switch, self.journal.prior_target)
        self._remove_candidate()

    def _abort(self, original_error, held):
        # A failed write/fsync may have persisted either record. Never promote
        # in-memory candidate provenance into recovery authority after an error.
        self.journal = self.store.load()
        if self.journal is None or self.journal.phase in TERMINAL:
            raise ValueError("Terminal/unknown transaction requires finalization, not rollback")
        mutated = self.journal.phase in MAY_WRITE_CONFIG
        try:
            self._stop_children()
            if self.journal.service_states and held:
                self._coherent_prior(mutated)
                self._gate("permit", self.journal.prior_target)
                self._service("start", UI)
                self._ready(self.journal.prior_target.name)
                self._gate("clear")
                self._restore_units(include_ui=True)
            else:
                self._remove_candidate()
                if self.journal.phase == "quiescing":
                    # No handle means no authority to stop jobs/writers. The
                    # request-tagged publication may nevertheless have replaced
                    # its leaf before fsync failed. Reconcile it durably before
                    # terminal success; unrelated/unsafe intent must block us.
                    self._effect(
                        "maintenance-clear",
                        maintenance.clear_request_intent,
                        self.paths,
                        self.journal.request_id,
                    )
            self._intent("rolled-back")
            self.store.publish_status(
                "rolled-back", "Update failed; previous release preserved", self.journal.request_id
            )
            return UpdateResult(
                "failed",
                self.journal.prior_target.name,
                original_error,
                "succeeded",
                self.journal.request_id,
            )
        except Exception as rollback_error:
            # Do not let a caught rollback exception turn the held maintenance
            # scope into a normal exit (which would clear its durable intent).
            try:
                self._intent("recovery-failed" if mutated else "recovery-failed-pre-mutation")
            except Exception:
                pass
            raise _RollbackFailed(original_error, type(rollback_error).__name__) from rollback_error

    def _transaction(self, request):
        prior, _ = _current_target(self.paths)
        self.journal = Journal(
            None,
            prior,
            None,
            self.worker_uid,
            request_id=request.request_id,
            channel=request.channel,
        )
        self.store.save(self.journal)
        self._boundary("intent:claimed")
        self.systemd.bind_request(request.request_id)
        self.store.publish_status("claimed", "Update request claimed", request.request_id)
        try:
            release, contract = self._prepare(request, prior.name)
            if release is None:
                self._intent("rolled-back")
                self.store.publish_status(
                    "rolled-back", "No newer compatible release", request.request_id
                )
                return UpdateResult("no-update", prior.name, request_id=request.request_id)
            # Capture ALL states before publishing maintenance, even if draining fails.
            self._capture()
            self._intent("quiescing")
            handle = maintenance.wait_for_quiescence(
                self.paths, self.drain_timeout, request_id=self.journal.request_id
            )
        except Exception as error:
            return self._abort(_diagnostic(error), held=False)
        with handle:
            try:
                self._boundary("effect:maintenance-acquired")
                self._gate("deny")
                self._stop_writers()
                self._intent("snapshotted")
                self._effect("snapshot", self.store.snapshot_config)
                original_raw = fs.read_regular(
                    self.paths.config_dir / "config.json", self.limits.CONFIG_BYTES
                )
                original = parse_object(original_raw, self.limits.CONFIG_BYTES)
                reject_credentials(original)
                validate_config_copy(
                    original,
                    {**original, "schema_version": contract.output_schema_version},
                    contract,
                )
                output = self._stage(
                    "migrate", {}, self.journal.candidate, {"config-input.json": original_raw}
                )
                migrated_raw = self._ingest(output, "config.json", self.limits.CONFIG_BYTES)
                migrated = parse_object(migrated_raw, self.limits.CONFIG_BYTES)
                reject_credentials(migrated)
                validate_config_copy(original, migrated, contract)
                with fs._parent(self.paths.config_dir / "config.json") as (
                    stack,
                    parent,
                    name,
                    chain,
                ):
                    entry = fs._open(stack, parent, name, {0}, os.fstat(parent).st_dev)
                    uid, gid, mode = (
                        entry.info.st_uid,
                        entry.info.st_gid,
                        stat.S_IMODE(entry.info.st_mode),
                    )
                    fs._check([*chain, entry])
                self._intent("config-written")
                self._gate("deny")
                self._effect(
                    "config",
                    fs.atomic_write,
                    self.paths.config_dir / "config.json",
                    migrated_raw,
                    uid,
                    gid,
                    mode,
                )
                self._intent("activated", candidate_published=True)
                self._effect("activate", self._switch, self.journal.candidate)
                self._intent("checking")
                self._gate("permit", self.journal.candidate)
                self._service("start", UI)
                self._ready(release.version)
                self._intent("committed")
            except Exception as error:
                result = self._abort(_diagnostic(error), held=True)
            else:
                # Committed journals are immutable. A finalization failure must
                # be reconciled as committed, NEVER as permission to roll back.
                self._gate("clear")
                self._restore_units()
                self.store.publish_status(
                    "committed", "Release update completed", request.request_id
                )
                result = UpdateResult("updated", release.version, request_id=request.request_id)
            self._intent()  # intent for the ownership handle's durable unlink
        self._boundary("effect:maintenance-release")
        return result

    def run(self) -> UpdateResult:
        try:
            with (
                fs.mount_anchors(
                    (self.paths.releases.parent, self.paths.config_dir, self.workspace_root)
                ),
                LifecycleLock(self.lock_path).acquire(),
            ):
                self._identities()
                self._layout()
                self.store = StateStore(self.paths)
                self.journal = self.store.load()
                if self.journal is not None:
                    self.systemd.bind_request(self.journal.request_id)
                    if self.journal.phase in ("recovery-failed", "recovery-failed-pre-mutation"):
                        return UpdateResult(
                            "blocked", error=ADMIN, request_id=self.journal.request_id
                        )
                    if self.journal.phase == "recovered-awaiting-start":
                        if _current_target(self.paths)[0] != self.journal.prior_target:
                            raise ValueError("Recovered target mismatch")
                        self._validate_target(self.journal.prior_target)
                        if not check_start_allowed(self.paths, "ui"):
                            raise ValueError("Recovered startup gate mismatch")
                        self._ready(self.journal.prior_target.name)
                        self._restore_units()
                        self._intent("rolled-back")
                        self._clear_maintenance()
                        self.store.reconcile_status()
                    elif self.journal.phase not in TERMINAL:
                        return self._recover_locked("boot")
                    elif self.journal.phase == "committed":
                        self._finalize_committed(start=True)
                    elif _current_target(self.paths)[0] != self.journal.prior_target:
                        raise ValueError("Rolled-back target mismatch")
                    else:
                        self.store.reconcile_status()
                self._layout(preparation=True)
                request = self._claim()
                return self._transaction(request)
        except BlockingIOError:
            return UpdateResult("busy", error="Lifecycle operation already active")
        except _RollbackFailed as error:
            try:
                self.store.publish_status(
                    self.journal.phase,
                    "Update recovery requires administrator intervention",
                    self.journal.request_id,
                )
            except Exception:
                pass  # Private journal/intent evidence, not status, remains authoritative.
            return UpdateResult(
                "failed",
                error=error.original,
                rollback_status="failed: " + error.rollback + "; " + ADMIN,
                request_id=self.journal.request_id,
            )
        except Exception as error:
            return UpdateResult(
                "blocked",
                error=_diagnostic(error) + "; " + ADMIN,
                request_id=None if self.journal is None else self.journal.request_id,
            )

    def _finalize_committed(self, start):
        self._stop_children()
        if _current_target(self.paths)[0] != self.journal.candidate:
            raise ValueError("Committed target mismatch")
        self._validate_target(self.journal.candidate)
        # If a crash left a permit, its config digest must still match before
        # clearing. A deny gate after commit is not a coherent committed state.
        if not check_start_allowed(self.paths, "ui"):
            raise ValueError("Committed configuration/gate mismatch")
        if not maintenance.maintenance_requested(self.paths) and check_start_allowed(
            self.paths, "cleanup"
        ):
            self.store.reconcile_status()
            return  # fully finalized: do not undo later administrator unit choices
        self._gate("clear")
        if start:
            self._restore_units()
        self._clear_maintenance()
        self.store.reconcile_status()

    def _recover_locked(self, mode):
        self.systemd.verify_recovery_preconditions(mode)
        journal = self.journal
        if journal is None:
            if maintenance.maintenance_requested(self.paths) or not check_start_allowed(
                self.paths, "cleanup"
            ):
                raise ValueError(
                    "Unjournaled maintenance/gate; administrator intervention required"
                )
            return UpdateResult("clean")
        self.systemd.bind_request(journal.request_id)
        if journal.phase == "committed":
            self._finalize_committed(start=False)
            return UpdateResult("clean", journal.candidate.name, request_id=journal.request_id)
        if journal.phase == "rolled-back":
            if _current_target(self.paths)[0] != journal.prior_target:
                raise ValueError("Rolled-back target mismatch")
            self._gate("clear")
            self._clear_maintenance()
            self.store.reconcile_status()
            return UpdateResult("clean", journal.prior_target.name, request_id=journal.request_id)
        if journal.service_states and set(journal.service_states) != SERVICES:
            raise ValueError("Incomplete recovery unit states")
        # Recovery holds the existing intent and exclusive lease even though it
        # never starts/probes UI. Reconcile protected intent only after coherence.
        if not journal.service_states:
            self._capture()
        with self._recovery_lease():
            self._stop_children()
            if journal.phase == "recovered-awaiting-start":
                if _current_target(self.paths)[0] != journal.prior_target:
                    raise ValueError("Recovered target mismatch")
                self._validate_target(journal.prior_target)
            else:
                self._coherent_prior(journal.phase in MAY_WRITE_CONFIG, stop_writers=False)
            self._gate("clear")
            self._intent("recovered-awaiting-start")
            self._clear_maintenance()
            self.store.reconcile_status()
        return UpdateResult("recovered", journal.prior_target.name, request_id=journal.request_id)

    def recover(self, mode: str) -> UpdateResult:
        if mode not in ("boot", "offline"):
            raise ValueError("Recovery mode must be boot or offline")
        try:
            with (
                fs.mount_anchors(
                    (self.paths.releases.parent, self.paths.config_dir, self.workspace_root)
                ),
                LifecycleLock(self.lock_path).acquire(),
            ):
                self._identities()
                self._layout()
                self.systemd.verify_recovery_preconditions(mode)
                self.store = StateStore(self.paths)
                self.journal = self.store.load()
                return self._recover_locked(mode)
        except BlockingIOError:
            return UpdateResult("busy", error="Lifecycle operation already active")
        except Exception as error:
            return UpdateResult(
                "blocked",
                error=_diagnostic(error) + "; " + ADMIN,
                request_id=None if self.journal is None else self.journal.request_id,
            )

    def check_clean_state(self) -> UpdateResult:
        try:
            with (
                fs.mount_anchors(
                    (self.paths.releases.parent, self.paths.config_dir, self.workspace_root)
                ),
                LifecycleLock(self.lock_path).acquire(),
            ):
                self._identities()
                self._layout()
                store = StateStore(self.paths)
                journal = store.load()
                if journal is not None and journal.phase not in TERMINAL:
                    raise ValueError("Recover uncommitted transaction before installer changes")
                if journal is not None:
                    target = (
                        journal.candidate if journal.phase == "committed" else journal.prior_target
                    )
                    if _current_target(self.paths)[0] != target:
                        raise ValueError("Terminal journal/current mismatch")
                if maintenance.maintenance_requested(self.paths) or not check_start_allowed(
                    self.paths, "cleanup"
                ):
                    raise ValueError("Unreconciled maintenance/gate")
                return UpdateResult("clean")
        except BlockingIOError:
            return UpdateResult("busy", error="Lifecycle operation already active")
        except Exception as error:
            return UpdateResult("blocked", error=_diagnostic(error) + "; " + ADMIN)


class _RollbackFailed(RuntimeError):
    def __init__(self, original, rollback):
        self.original, self.rollback = original, rollback


def _json(value):
    return json.dumps(value, allow_nan=False, separators=(",", ":")).encode("utf-8")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Protected transactional release coordinator")
    modes = parser.add_mutually_exclusive_group(required=True)
    for name in ("run", "recover-boot", "recover-offline", "check-clean-state"):
        modes.add_argument("--" + name, action="store_true")
    parser.add_argument("--paths-file", type=Path, default=Path("/etc/knx_to_openhab/paths.env"))
    args = parser.parse_args(argv)
    try:
        if not sys.flags.isolated or os.geteuid() != 0:
            raise ValueError("Coordinator requires isolated system Python as root")
        os.environ.clear()
        os.environ.update({"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"})
        os.chdir("/")
        os.umask(0o077)
        from uuid import uuid4

        paths = load_paths(args.paths_file)
        updater = ReleaseUpdater(paths, SystemdAdapter(str(uuid4())), Limits())
        if args.run:
            result = updater.run()
        elif args.check_clean_state:
            result = updater.check_clean_state()
        else:
            result = updater.recover("boot" if args.recover_boot else "offline")
    except Exception as error:
        result = UpdateResult("blocked", error=_diagnostic(error) + "; " + ADMIN)
    print(json.dumps(asdict(result), separators=(",", ":")))
    return 0 if result.status in ("updated", "no-update", "recovered", "clean") else 1
