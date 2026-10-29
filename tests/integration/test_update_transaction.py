"""Assembled real-FS/real-worker/real-HTTP lifecycle with a FAKE service manager.

No live systemd, sudo, account provisioning, or installed paths are touched.
The opt-in disposable-manager acceptance suite is separate.
"""

import hashlib
import io
import json
import os
import signal
import socket
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
import requests

from installer.update_core.protocol import Limits, Paths
from installer.update_core.state import StateStore, check_start_allowed, write_gate
from installer.update_core.systemd import SERVICES, STAGES, ServiceState
from installer.update_core.transaction import ReleaseUpdater

ROOT = Path(__file__).resolve().parents[2]
PROCESS = Path(__file__).with_name("update_fixture_process.py")
WORKER = 65534
SERVICE = 65533


def source_files(version):
    files = {"VERSION": (version + "\n").encode(), "requirements.txt": b""}
    for pattern in ("*.py", "web_ui/backend/*.py", "installer/*.py", "installer/update_core/*.py"):
        for path in ROOT.glob(pattern):
            files[path.relative_to(ROOT).as_posix()] = path.read_bytes()
    files["installer/update_contract.json"] = (ROOT / "installer/update_contract.json").read_bytes()
    return files


def release_archive(version):
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w:gz") as archive:
        for name, contents in source_files(version).items():
            info = tarfile.TarInfo(f"knx_to_openhab-{version}/{name}")
            info.size = len(contents)
            info.mode = 0o644
            archive.addfile(info, io.BytesIO(contents))
    return raw.getvalue()


def make_updater(f):
    return ReleaseUpdater(
        f.paths,
        f.manager,
        Limits(),
        lock_path=f.root / "lifecycle.lock",
        workspace_root=f.root / "prepare",
        worker_uid=WORKER,
        worker_gid=WORKER,
        service_uid=SERVICE,
        readiness_timeout=0.5,
        drain_timeout=0.1,
    )


def crash_coordinator(context, boundary):
    values = json.loads(Path(context).read_text())
    paths = Paths(*(Path(p) for p in values.pop("paths")))
    f = SimpleNamespace(**values, paths=paths)
    f.root = Path(f.root)
    f.manager = LocalManager(f)
    updater = make_updater(f)
    updater._boundary = lambda label: os._exit(73) if label == boundary else None
    result = updater.run()
    print(result, flush=True)
    os._exit(74)


class LocalManager:
    """Fake unit effects, REAL demoted worker processes and application HTTP.

    Process groups here are test cleanup, NOT evidence for cgroup confinement.
    """

    def __init__(self, fixture):
        self.fixture = fixture
        self.active = dict.fromkeys(SERVICES, False)
        self.enabled = dict.fromkeys(SERVICES, True)
        self.stopped = set()
        self.process = None
        self.fail_stage = ""
        self.bad_health = False
        self.events = []

    def bind_request(self, request_id):
        self.request_id = request_id
        self.stopped.clear()

    def stop_children(self, request_id):
        assert request_id == self.request_id
        self.stopped = set(STAGES)  # fake-manager proof, never real-systemd evidence

    def capture_services(self):
        return ServiceState(self.active.copy(), self.enabled.copy())

    def run_child(self, stage, paths, workspace, candidate):
        self.stopped.clear()
        self.events.append(stage)
        result = subprocess.run(
            [
                sys.executable,
                str(PROCESS),
                "stage",
                str(ROOT),
                stage,
                str(workspace),
                str(candidate) if candidate else "",
                self.fixture.http_url,
                self.fail_stage,
            ],
            check=False,
            user=WORKER,
            group=WORKER,
            extra_groups=(),
            cwd="/",
            env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"},
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=90,
        )
        if result.returncode:
            self.fixture.stage_error = result.stderr.decode(errors="replace")
            print(self.fixture.stage_error)
            raise subprocess.CalledProcessError(result.returncode, result.args)

    def stop_app(self):
        if self.process is not None:
            try:
                os.killpg(self.process.pid, signal.SIGTERM)
                self.process.wait(timeout=5)
            finally:
                try:
                    os.killpg(self.process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            self.process = None

    def service(self, action, name):
        assert name in SERVICES
        self.events.append((action, name))
        if action in ("enable", "disable"):
            self.enabled[name] = action == "enable"
            return
        if name == SERVICES[0]:
            if action == "stop":
                self.stop_app()
            elif self.process is None:
                f = self.fixture
                assert check_start_allowed(f.paths, "ui")
                env = os.environ.copy()
                env.update(f.environment())
                self.process = subprocess.Popen(
                    [
                        sys.executable,
                        str(PROCESS),
                        "app",
                        str(f.paths.current.resolve()),
                        str(f.paths.data_dir),
                        str(f.port),
                        (
                            "yes"
                            if self.bad_health and f.paths.current.resolve().name != "1.0.0"
                            else "no"
                        ),
                    ],
                    user=SERVICE,
                    group=SERVICE,
                    extra_groups=(),
                    env=env,
                    cwd="/",
                    start_new_session=True,
                    stdout=f.app_log,
                    stderr=f.app_log,
                )
                deadline = time.monotonic() + 10
                while True:
                    assert self.process.poll() is None, (f.root / "app.log").read_text()
                    try:
                        if requests.get(f.app_url + "/api/health", timeout=0.2).status_code == 200:
                            break
                    except requests.RequestException:
                        pass
                    assert time.monotonic() < deadline, (f.root / "app.log").read_text()
                    time.sleep(0.02)
        elif action == "start":
            assert check_start_allowed(self.fixture.paths, "cleanup")
        self.active[name] = action == "start"

    def notify_ready(self, timeout=30):
        # Explicit fake notify state; HTTP below is actual application readiness.
        return self.process is not None and self.process.poll() is None


@pytest.fixture
def assembled():
    if os.name != "posix" or os.geteuid() != 0:
        pytest.skip("Linux root-private fixture demotes all candidate/application execution")
    from web_ui.backend.session_store import SessionStore
    from web_ui.backend.storage import save_jobs

    with tempfile.TemporaryDirectory(prefix="knxoh-assembled-", dir="/run") as directory:
        root = Path(directory)
        root.chmod(0o755)
        names = ("custom app", "custom config", "custom data", "custom backups", "prepare")
        for name in names:
            (root / name).mkdir(mode=0o755)
        releases = root / names[0] / "releases"
        releases.mkdir()
        old = releases / "1.0.0"
        old.mkdir()
        for name, raw in source_files("1.0.0").items():
            path = old / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
            path.chmod(0o644)
        current = releases.parent / "current"
        current.symlink_to(old)
        paths = Paths(releases, current, root / names[1], root / names[2], root / names[3])
        StateStore(paths).publish_status("rolled-back", "No update requested")
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        config = paths.config_dir / "config.json"
        config.write_text(
            json.dumps(
                {"auth": {"enabled": False}, "port": port, "sibling": {"preserved": [1, True]}}
            )
            + "\n"
        )
        config.chmod(0o640)
        os.chown(config, 0, SERVICE)
        for name, raw in (
            ("secrets.env", b"fixture-secret\n"),
            ("generator.json", b"{}\n"),
            (".updater-mutation.lock", b""),
        ):
            path = paths.config_dir / name
            path.write_bytes(raw)
            path.chmod(0o660 if name.endswith(".lock") else 0o640)
            os.chown(path, 0, SERVICE)
        save_jobs(
            str(paths.data_dir / "jobs"),
            {"existing": {"id": "existing", "status": "completed", "stats": {"count": 7}}},
        )
        store = SessionStore(paths.data_dir / "sessions.sqlite3", b"fixture-session-key" * 2)
        token, csrf = store.create("operator")
        (paths.data_dir / "context.json").write_text(json.dumps({"token": token, "csrf": csrf}))
        for base in (paths.data_dir, paths.backup_dir):
            (base / "unrelated-sentinel").write_bytes(b"never restore a whole data directory")
            for path in [base, *base.rglob("*")]:
                os.chown(path, SERVICE, SERVICE)
        f = SimpleNamespace(root=root, paths=paths, port=port, version="2.0.0", corrupt=False)
        f.app_url = f"http://127.0.0.1:{port}"
        f.app_log = (root / "app.log").open("w")
        payloads = {v: release_archive(v) for v in ("2.0.0", "2.1.0-rc.1", "1.0.0")}

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                version = f.version
                name = f"knx_to_openhab-{version}.tar.gz"
                url = f"https://github.com/diddip21/knx_to_openhab/releases/download/v{version}/"
                metadata = {
                    "tag_name": "v" + version,
                    "draft": False,
                    "prerelease": "-" in version,
                    "assets": [
                        {"name": n, "browser_download_url": url + n}
                        for n in (name, name + ".sha256")
                    ],
                }
                if self.path == "/metadata":
                    # run_stage wraps a prerelease listing in its own pages array.
                    value = [metadata] if "-" in version else metadata
                    raw = json.dumps(value).encode()
                elif self.path.endswith(".sha256"):
                    digest = hashlib.sha256(payloads[version]).hexdigest()
                    raw = f"{digest}  {name}\n".encode()
                else:
                    raw = b"bad artifact" if f.corrupt else payloads[version]
                self.send_response(200)
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def log_message(self, *_args):
                pass

        http = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=http.serve_forever, daemon=True)
        thread.start()
        f.http_url = f"http://127.0.0.1:{http.server_port}"
        f.environment = lambda: {
            "KNXOH_INSTALL_DIR": str(releases.parent),
            "KNXOH_CONFIG_DIR": str(paths.config_dir),
            "KNXOH_DATA_DIR": str(paths.data_dir),
            "KNXOH_BACKUP_DIR": str(paths.backup_dir),
            "KNXOH_PATHS_FILE": str(root / "absent.env"),
            "FLASK_ENV": "testing",
        }
        manager = LocalManager(f)
        f.manager = manager
        f.updater = lambda: make_updater(f)
        f.request = lambda channel="stable": publish_request(paths, channel)
        try:
            manager.service("start", SERVICES[0])
            yield f
        finally:
            manager.stop_app()
            f.app_log.close()
            http.shutdown()
            http.server_close()
            thread.join(timeout=5)


def publish_request(paths, channel):
    update = paths.data_dir / "update"
    update.mkdir(mode=0o700, exist_ok=True)
    os.chown(update, SERVICE, SERVICE)
    request_id = str(uuid4())
    path = update / "request.json"
    path.write_text(json.dumps({"format_version": 1, "request_id": request_id, "channel": channel}))
    path.chmod(0o600)
    os.chown(path, SERVICE, SERVICE)
    return request_id


def assert_shared_state(f, versions):
    from web_ui.backend.storage import load_jobs

    jobs = load_jobs(str(f.paths.data_dir / "jobs"))
    assert jobs["existing"]["stats"] == {"count": 7}
    assert all("written-" + version in jobs for version in versions)
    for directory in (f.paths.data_dir, f.paths.backup_dir):
        assert (
            directory / "unrelated-sentinel"
        ).read_bytes() == b"never restore a whole data directory"
    assert (f.paths.config_dir / "secrets.env").read_bytes() == b"fixture-secret\n"
    assert (f.paths.config_dir / "generator.json").read_bytes() == b"{}\n"
    info = (f.paths.config_dir / "config.json").stat()
    assert (info.st_uid, info.st_gid, info.st_mode & 0o777) == (0, SERVICE, 0o640)
    assert requests.get(f.app_url + "/api/jobs", timeout=2).status_code == 200


@pytest.mark.parametrize("channel,version", [("stable", "2.0.0"), ("prerelease", "2.1.0-rc.1")])
def test_real_stages_custom_paths_success(assembled, channel, version):
    f = assembled
    f.version = version
    request_id = f.request(channel)
    result = f.updater().run()
    assert result.status == "updated", (result, getattr(f, "stage_error", ""))
    assert result.request_id == request_id
    assert f.paths.current.resolve().name == version
    assert StateStore(f.paths).load().phase == "committed"
    assert json.loads((f.paths.config_dir / "config.json").read_bytes())["sibling"] == {
        "preserved": [1, True]
    }
    assert_shared_state(f, ["1.0.0", version])


@pytest.mark.parametrize("failure", ["current", "artifact", "migrate", "health"])
def test_real_failure_keeps_old_app_and_shared_records(assembled, failure):
    f = assembled
    original = (f.paths.config_dir / "config.json").read_bytes()
    if failure == "current":
        f.version = "1.0.0"
    elif failure == "artifact":
        f.corrupt = True
    elif failure == "migrate":
        f.manager.fail_stage = "migrate"
    else:
        f.manager.bad_health = True
    f.request()
    result = f.updater().run()
    assert result.status == ("no-update" if failure == "current" else "failed"), result
    assert f.paths.current.resolve().name == "1.0.0"
    assert (f.paths.config_dir / "config.json").read_bytes() == original
    assert_shared_state(f, ["1.0.0", "2.0.0"] if failure == "health" else ["1.0.0"])
    assert requests.get(f.app_url + "/api/health", timeout=2).json()["version"] == "1.0.0"
    if failure == "health":
        starts = json.loads((f.paths.data_dir / "startup-evidence.json").read_text())
        assert [s["version"] for s in starts] == ["1.0.0", "2.0.0", "1.0.0"]
        assert "written-2.0.0" in starts[-1]["read_jobs"]
        assert "writer-2.0.0" in starts[-1]["read_sessions"]
        assert starts[-1]["source"] == str(f.paths.releases / "1.0.0")


def test_failed_dependencies_retry_same_version_fresh_candidate(assembled):
    f = assembled
    f.manager.fail_stage = "dependencies"
    first = f.request()
    failed = f.updater().run()
    assert failed.status == "failed" and failed.rollback_status == "succeeded", failed
    assert not (f.paths.releases / f.version).exists()
    f.manager.fail_stage = ""
    assert f.request() != first
    result = f.updater().run()
    assert result.status == "updated", result
    assert not (f.paths.current.resolve() / "poison-partial-venv").exists()
    assert_shared_state(f, ["1.0.0", "2.0.0"])


def test_real_submission_claim_and_completed_projection(assembled, monkeypatch):
    f = assembled
    paths = json.dumps(
        [
            str(p)
            for p in (
                f.paths.releases,
                f.paths.current,
                f.paths.config_dir,
                f.paths.data_dir,
                f.paths.backup_dir,
            )
        ]
    )
    client = subprocess.Popen(
        [sys.executable, str(PROCESS), "submit", str(ROOT), paths],
        user=SERVICE,
        group=SERVICE,
        extra_groups=(),
        cwd="/",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + 10
        while not (f.paths.data_dir / "submission-started").exists():
            assert client.poll() is None, client.communicate(timeout=2)
            assert time.monotonic() < deadline
            time.sleep(0.02)
        result = f.updater().run()
        out, err = client.communicate(timeout=10)
        assert client.returncode == 0, err
        submitted = json.loads(out)
        assert submitted["status"] == "submitted", submitted
        assert submitted["request_id"] == result.request_id
        assert result.status == "updated", result
        # Actual application consumer reads the coordinator's root-authored file.
        from web_ui.backend.updater import Updater

        for key, value in f.environment().items():
            monkeypatch.setenv(key, value)
        facade = Updater(base_path=str(f.paths.current.resolve()))
        projection = facade.get_update_status()
        assert projection["request_id"] == result.request_id
        assert projection["outcome"] == "updated" and projection["phase"] == "committed"
    finally:
        if client.poll() is None:
            client.kill()
            client.communicate(timeout=5)


def test_installer_and_update_share_actual_kernel_lock(assembled):
    f = assembled
    f.request()
    # A separate administrator process holds the actual bootstrap's lease class,
    # not a boolean busy stub or two threads sharing a descriptor.
    installer = subprocess.Popen(
        [sys.executable, str(PROCESS), "installer-lock", str(ROOT), str(f.root / "lifecycle.lock")],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert installer.stdout.readline().strip() == "locked"
        result = f.updater().run()
        assert result.status == "busy", result
    finally:
        installer.communicate("\n", timeout=5)
        assert installer.returncode == 0
    assert f.updater().run().status == "updated"


@pytest.mark.parametrize("boundary", ["effect:config", "effect:activate"])
def test_killed_coordinator_gate_and_boot_recovery(assembled, boundary):
    f = assembled
    original = (f.paths.config_dir / "config.json").read_bytes()
    f.request()
    # A fresh trusted coordinator process exits without Python cleanup/rollback.
    # No fork from the threaded HTTP fixture and no manager/host process is killed.
    f.manager.stop_app()
    context = f.root / "coordinator.json"
    context.write_text(
        json.dumps(
            {
                "paths": [
                    str(p)
                    for p in (
                        f.paths.releases,
                        f.paths.current,
                        f.paths.config_dir,
                        f.paths.data_dir,
                        f.paths.backup_dir,
                    )
                ],
                "root": str(f.root),
                "http_url": f.http_url,
            }
        )
    )
    result = subprocess.run(
        [sys.executable, str(PROCESS), "coordinator", str(ROOT), str(context), boundary],
        capture_output=True,
        timeout=90,
    )
    assert result.returncode == 73, (result.stdout, result.stderr)
    for role in ("ui", "cleanup"):
        assert not check_start_allowed(f.paths, role)
    recovery = f.updater().recover("boot")
    assert recovery.status == "recovered", recovery
    assert f.paths.current.resolve().name == "1.0.0"
    assert (f.paths.config_dir / "config.json").read_bytes() == original
    f.manager.service("start", SERVICES[0])
    assert_shared_state(f, ["1.0.0"])
    # A corrupt protected journal fails closed and cannot bless writer startup.
    write_gate(f.paths, "deny", None, None)
    (f.paths.config_dir / ".updater-state/journal.json").write_bytes(b"{corrupt")
    assert f.updater().recover("boot").status == "blocked"
    assert not check_start_allowed(f.paths, "ui")
    assert not check_start_allowed(f.paths, "cleanup")
