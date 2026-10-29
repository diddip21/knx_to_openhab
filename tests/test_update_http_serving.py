"""Real nonprivileged local Gunicorn, deployed config, actual API/submission wait.

No systemd/sudo operations: replace only the manager adapter and administrator
claim publication in disposable files. Do not shorten the 30-second ack policy.
"""

import json
import os
import runpy
import signal
import socket
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
import requests

from installer import update_submit
from web_ui.backend import storage

ROOT = Path(__file__).resolve().parents[1]


def test_deployed_gunicorn_covers_complete_submission_budget_and_keeps_ui_available(monkeypatch):
    monkeypatch.setattr(storage, "load_config", lambda: {"bind_host": "127.0.0.1", "port": 8085})
    conf = runpy.run_path(str(ROOT / "web_ui/backend/gunicorn_conf.py"))
    assert update_submit.COMMAND_TIMEOUT_SECONDS == 5
    complete_wait = 3 * update_submit.COMMAND_TIMEOUT_SECONDS + update_submit.ACK_TIMEOUT
    assert update_submit.SUBMISSION_WAIT_SECONDS == complete_wait
    assert update_submit.ACK_TIMEOUT == update_submit.STALE_SECONDS == 30
    assert conf.get("timeout", 30) > complete_wait
    assert conf.get("workers", 1) == 1  # Do not duplicate process-local job state.
    assert conf.get("worker_class", "sync") == "gthread"
    assert conf.get("threads", 1) >= 4


@pytest.mark.skipif(os.name != "posix", reason="Gunicorn/UID isolation requires Linux")
@pytest.mark.parametrize("ack", [False, True], ids=["no-ack", "late-ack"])
def test_real_gunicorn_survives_full_ack_window_and_serves_other_requests(ack):
    if os.geteuid() != 0:
        pytest.skip("root-private fixture demotes only its child server to UID 65534")
    pytest.importorskip("gunicorn")
    with tempfile.TemporaryDirectory(prefix="task8-http-", dir="/run") as directory:
        root = Path(directory)
        root.chmod(0o755)
        for name in ("releases", "releases/1.0.0", "config", "data", "backup"):
            (root / name).mkdir(mode=0o755)
        (root / "current").symlink_to(root / "releases/1.0.0")
        os.chown(root / "data", 65534, 65534)
        lock = root / "config/.updater-mutation.lock"
        lock.touch(mode=0o660)
        lock.chmod(0o660)
        os.chown(lock, 0, 65534)
        (root / "config/config.json").write_text(json.dumps({"auth": {"enabled": False}}))
        _status(root, None)
        (root / "fixture_app.py").write_text("""
import json,os,time
from pathlib import Path
from subprocess import CompletedProcess
from installer import update_submit as s
data=Path(os.environ['KNXOH_DATA_DIR'])
def manager(argv,**kwargs):
    assert kwargs['timeout']==5
    time.sleep(4.2)  # each of the three bounded manager operations is slow
    if argv==[s.SYSTEMCTL,'show',s.UNIT,'--property=LoadState,ActiveState,SubState,Job','--all','--no-pager']:
        return CompletedProcess(argv,0,'LoadState=loaded\\nActiveState=inactive\\nSubState=dead\\nJob=\\n','')
    assert argv==['sudo','-n',s.SYSTEMCTL,'start','--no-block',s.UNIT],argv
    request=json.loads((data/'update/request.json').read_bytes())
    marker=data/'started.tmp'
    marker.write_text(json.dumps(dict(request_id=request['request_id'],pid=os.getpid())))
    marker.replace(data/'started.json')
    return CompletedProcess(argv,0,'','')
s.subprocess.run=manager
from web_ui.backend.app import app
@app.after_request
def identify_worker(response):
    response.headers['X-Fixture-Worker']=str(os.getpid())
    return response
""")
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        url = f"http://127.0.0.1:{port}"
        env = os.environ.copy()
        env.update(
            {
                "KNXOH_INSTALL_DIR": str(root),
                "KNXOH_CONFIG_DIR": str(root / "config"),
                "KNXOH_DATA_DIR": str(root / "data"),
                "KNXOH_BACKUP_DIR": str(root / "backup"),
                "KNXOH_PATHS_FILE": str(root / "missing.env"),
                "PYTHONPATH": os.pathsep.join([str(root), str(ROOT)]),
                "FLASK_ENV": "testing",
                "PATH": os.environ["PATH"],
            }
        )
        output = root / "gunicorn.log"
        with output.open("w+") as log:
            server = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "gunicorn",
                    "-c",
                    str(ROOT / "web_ui/backend/gunicorn_conf.py"),
                    "--bind",
                    f"127.0.0.1:{port}",
                    "fixture_app:app",
                ],
                cwd=ROOT,
                env=env,
                user=65534,
                group=65534,
                extra_groups=(),
                start_new_session=True,
                stdout=log,
                stderr=log,
            )
            try:
                deadline = time.monotonic() + 15
                while True:
                    try:
                        initial = requests.get(url + "/api/version", timeout=1)
                        if initial.status_code == 200:
                            break
                    except requests.RequestException:
                        pass
                    assert server.poll() is None, output.read_text()
                    assert time.monotonic() < deadline, output.read_text()
                    time.sleep(0.05)
                with ThreadPoolExecutor(max_workers=1) as pool:
                    start = time.monotonic()
                    pending = pool.submit(requests.post, url + "/api/version/update", timeout=60)
                    deadline = time.monotonic() + 20
                    marker = root / "data/started.json"
                    while not marker.exists() and time.monotonic() < deadline:
                        assert not pending.done(), pending.result().text
                        time.sleep(0.05)
                    assert marker.exists(), output.read_text()
                    request = json.loads(marker.read_text())
                    responsive = False
                    try:
                        probe_start = time.monotonic()
                        probe = requests.get(url + "/api/version", timeout=2)
                        responsive = probe.status_code == 200 and time.monotonic() - probe_start < 2
                    except requests.RequestException:
                        pass
                    if ack:
                        # A real late claim, 28 seconds AFTER the three slow ops.
                        time.sleep(28)
                        _status(root, request["request_id"])
                    response = pending.result(timeout=45)
                    elapsed = time.monotonic() - start
                    assert responsive, "UI unavailable while synchronous submission waits"
                    assert elapsed > 39, elapsed
                    assert response.status_code == (200 if ack else 500), response.text
                    if ack:
                        assert response.json()["request_id"] == request["request_id"]
                        assert response.json()["status"] == "updating"
                    else:
                        assert "No matching updater acknowledgement" in response.json()["error"]
                        assert elapsed >= 42
                    assert (
                        response.headers["X-Fixture-Worker"] == initial.headers["X-Fixture-Worker"]
                    )
                    assert (
                        json.loads((root / "data/update/request.json").read_bytes())["request_id"]
                        == request["request_id"]
                    )
                    print(
                        f"{ack=}: HTTP {response.status_code}, elapsed={elapsed:.2f}s, UI responsive, same worker"
                    )
            finally:
                # This private session contains ONLY the disposable manager and
                # workers. Never leave orphan workers after a test assertion/timeout.
                try:
                    os.killpg(server.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    server.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(server.pid, signal.SIGKILL)
                    server.wait(timeout=5)
                finally:
                    try:
                        os.killpg(server.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass


def _status(root, request_id):
    value = {"format_version": 1, "phase": "rolled-back", "message": "No update requested"}
    if request_id:
        value.update(request_id=request_id, phase="claimed", message="Update request claimed")
    temporary = root / "config/status.tmp"
    temporary.write_text(json.dumps(value))
    temporary.replace(root / "config/.updater-status.json")
