"""Fixed argv adapter. No request-supplied commands, services, or sandbox overrides."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from uuid import UUID

from .protocol import Limits, Paths

STAGES = ("metadata", "download", "extract", "dependencies", "migrate")
ENV = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"}
SERVICES = ("knxohui.service", "knxohui-backup-cleanup.service", "knxohui-backup-cleanup.timer")


@dataclass(frozen=True)
class ServiceState:
    active: dict[str, bool]
    enabled: dict[str, bool]


def _path(path: Path) -> str:
    """Reject controls, backslashes, quotes, percent specifiers and dollar signs.

    Dollar syntax is intentionally unsupported: systemd expands ExecStart
    environment references even without a shell. Refuse it before launch rather
    than requiring systemd 254's --expand-environment option. Spaces remain valid.
    """
    value = path.as_posix()
    parsed = PurePosixPath(value)
    if (
        not parsed.is_absolute()
        or str(parsed) != value
        or ".." in parsed.parts
        or value == "/"
        or any(ord(c) < 32 or c in '\\"%$\x7f' for c in value)
    ):
        raise ValueError("Unsafe sandbox path")
    return value


def _quoted(path: Path) -> str:
    # systemd's property parser, not a shell. Reject escaping/specifier syntax.
    return '"' + _path(path) + '"'


class SystemdAdapter:
    def __init__(self, request_id: str, *, runner=subprocess.run):
        if str(UUID(request_id)) != request_id:
            raise ValueError("Expected canonical request UUID")
        self.request_id = request_id
        self.runner = runner
        self.stopped = set()

    def bind_request(self, request_id: str) -> None:
        if str(UUID(request_id)) != request_id:
            raise ValueError("Expected canonical request UUID")
        self.request_id = request_id
        self.stopped.clear()

    def service(self, action: str, name: str) -> None:
        if action not in ("start", "stop", "enable", "disable") or name not in SERVICES:
            raise ValueError("Unsupported fixed service operation")
        # Nonblocking start: coordinator enforces its own combined notify/HTTP
        # 60-second deadline rather than inheriting a systemd start timeout.
        options = ["--no-block"] if action == "start" else []
        self._run(["/usr/bin/systemctl", action, *options, "--", name])

    def notify_ready(self, timeout: float = 30) -> bool:
        result = self._run(
            [
                "/usr/bin/systemctl",
                "show",
                "--property=Type",
                "--property=ActiveState",
                "--property=SubState",
                "--",
                "knxohui.service",
            ],
            timeout=timeout,
        )
        fields = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
        return fields == {"Type": "notify", "ActiveState": "active", "SubState": "running"}

    def _unit(self, stage):
        return f"knxohupdate-{self.request_id}-{stage}.service"

    def _run(self, argv, timeout=30):
        return self.runner(
            argv,
            check=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
            env=ENV.copy(),
            cwd="/",
        )

    def _stop(self, stage):
        self.stopped.discard(stage)
        unit = self._unit(stage)
        stop_error = None
        try:
            self._run(["/usr/bin/systemctl", "stop", "--", unit])
        except subprocess.CalledProcessError as error:
            stop_error = error
        result = self._run(
            [
                "/usr/bin/systemctl",
                "show",
                "--property=ActiveState",
                "--property=ControlGroup",
                "--property=LoadState",
                "--",
                unit,
            ]
        )
        fields = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
        if stop_error is not None and fields.get("LoadState") != "not-found":
            raise stop_error
        if (
            fields.get("ActiveState") not in ("inactive", "failed")
            or fields.get("ControlGroup") != ""
        ):
            raise ValueError("Child cgroup teardown could not be confirmed")
        self.stopped.add(stage)

    def stop_children(self, request_id: str) -> None:
        if request_id != self.request_id:
            raise ValueError("Unrelated child request")
        errors = []
        for stage in STAGES:
            try:
                self._stop(stage)
            except (ValueError, subprocess.SubprocessError) as error:
                errors.append(error)
        if errors:
            raise ValueError("Cannot confirm all child cgroups stopped") from errors[0]

    def run_child(self, stage: str, paths: Paths, workspace: Path, candidate: Path | None) -> None:
        if stage not in STAGES or any(
            path is None for path in (paths.config_dir, paths.data_dir, paths.backup_dir)
        ):
            raise ValueError("Unknown child stage or missing protected external paths")
        _path(workspace)
        hidden = [paths.config_dir]
        hidden.extend(path for path in (paths.data_dir, paths.backup_dir) if path is not None)
        for path in (paths.releases, paths.current, *hidden):
            _path(path)
        if stage in ("extract", "dependencies", "migrate") and candidate is None:
            raise ValueError("Candidate required")
        if candidate is not None:
            if PurePosixPath(_path(candidate)).parent != PurePosixPath(_path(paths.releases)):
                raise ValueError("Candidate outside protected releases")
        writable = [workspace / "output"]
        if stage in ("extract", "dependencies"):
            writable.append(candidate)
        for write in writable:
            for secret in hidden:
                left, right = PurePosixPath(_path(write)), PurePosixPath(_path(secret))
                if left == right or left in right.parents or right in left.parents:
                    raise ValueError("Sandbox workspace overlaps live state")
        timeout = (
            Limits.DEPENDENCY_TIMEOUT_SECONDS
            if stage == "dependencies"
            else Limits.CHILD_TIMEOUT_SECONDS
        )
        properties = [
            "User=knxohupdate",
            "Group=knxohupdate",
            "SupplementaryGroups=",
            "NoNewPrivileges=yes",
            "ProtectSystem=strict",
            "ProtectHome=yes",
            "PrivateTmp=yes",
            "PrivateDevices=yes",
            "CapabilityBoundingSet=",
            "AmbientCapabilities=",
            "RestrictSUIDSGID=yes",
            "RestrictNamespaces=yes",
            "ProtectKernelTunables=yes",
            "ProtectKernelModules=yes",
            "ProtectControlGroups=yes",
            "RestrictRealtime=yes",
            "LockPersonality=yes",
            "RemoveIPC=yes",
            "KillMode=control-group",
            "SendSIGKILL=yes",
            "TimeoutStopSec=15",
            "UMask=0077",
            "TasksMax=64",
            "MemoryMax=1G",
            "LimitNOFILE=1024",
            "LimitCORE=0",
            f"LimitFSIZE={Limits.FILE_BYTES if stage not in ('download',) else Limits.ARCHIVE_BYTES}",
            f"RuntimeMaxSec={timeout}",
            "StandardOutput=null",
            "StandardError=null",
            "PrivateNetwork="
            + ("no" if stage in ("metadata", "download", "dependencies") else "yes"),
            "RestrictAddressFamilies="
            + (
                "AF_UNIX AF_INET AF_INET6"
                if stage in ("metadata", "download", "dependencies")
                else "AF_UNIX"
            ),
            "ReadWritePaths=" + " ".join(_quoted(path) for path in writable),
            "InaccessiblePaths=" + " ".join(_quoted(path) for path in hidden),
            "WorkingDirectory=/",
            "Environment=PATH=/usr/bin:/bin LANG=C.UTF-8",
        ]
        argv = ["/usr/bin/systemd-run", "--wait", "--quiet", "--unit=" + self._unit(stage)]
        argv += ["--property=" + property for property in properties]
        argv += [
            "--",
            "/usr/bin/python3",
            "-I",
            "/usr/local/libexec/knx_to_openhab/update_prepare.py",
            stage,
            "--workspace",
            _path(workspace),
        ]
        if candidate is not None:
            argv += ["--candidate", _path(candidate)]
        self.stopped.discard(stage)
        try:
            self._run(argv, timeout=timeout + 30)
        finally:
            # Unsupported properties, timeout, crash and successful exits all take
            # this same path. Never inspect output when stop/show fails.
            self._stop(stage)

    def capture_services(self) -> ServiceState:
        active, enabled = {}, {}
        for service in SERVICES:
            result = self._run(
                [
                    "/usr/bin/systemctl",
                    "show",
                    "--property=ActiveState",
                    "--property=UnitFileState",
                    "--",
                    service,
                ]
            )
            fields = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
            if fields.get("ActiveState") not in ("active", "inactive", "failed") or fields.get(
                "UnitFileState"
            ) not in ("enabled", "disabled", "static"):
                raise ValueError("Cannot capture stable service state")
            active[service] = fields["ActiveState"] == "active"
            enabled[service] = fields["UnitFileState"] == "enabled"
        return ServiceState(active, enabled)
