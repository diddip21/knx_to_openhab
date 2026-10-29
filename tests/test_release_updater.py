"""Real protected files plus a deterministic child/service boundary, never live units."""

import hashlib
import json
import os
import tempfile
from pathlib import Path
from uuid import uuid4

import pytest

from installer.update_core.protocol import Limits, Paths
from installer.update_core.state import StateStore, check_start_allowed
from installer.update_core.systemd import SERVICES, STAGES, ServiceState


class FakeSystemd:
    """Emulate *external* effects, not coordinator decisions or filesystem checks."""

    def __init__(self):
        self.request_id = None
        self.stopped = set()
        self.active = dict.fromkeys(SERVICES, True)
        self.enabled = dict.fromkeys(SERVICES, True)
        self.events = []
        self.fail = None
        self.version = "2.0.0"
        self.bad_copy = False
        self.bad_contract = False
        self.fail_old = False

    def bind_request(self, request_id):
        self.request_id = request_id

    def capture_services(self):
        return ServiceState(self.active.copy(), self.enabled.copy())

    def stop_children(self, request_id):
        assert request_id == self.request_id
        self.events.append("teardown")
        if self.fail == "teardown":
            self.stopped.clear()
            raise RuntimeError("cgroup teardown failed")
        self.stopped = set(STAGES)

    def run_child(self, stage, paths, workspace, candidate):
        self.events.append(stage)
        self.stopped.clear()
        assert workspace.stat().st_mode & 0o777 == 0o750
        assert workspace.stat().st_uid == 0 and workspace.stat().st_gid == 65534
        for name in ("input.json", "config-input.json", "verified.tar.gz"):
            path = workspace / name
            if path.exists():
                assert path.stat().st_mode & 0o777 == 0o440
                assert path.stat().st_uid == 0 and path.stat().st_gid == 65534
        if self.fail == stage:
            raise RuntimeError("child failure")
        output = workspace / "output"
        if stage == "metadata":
            name = f"knx_to_openhab-{self.version}.tar.gz"
            url = f"https://github.com/diddip21/knx_to_openhab/releases/download/v{self.version}/"
            data = {
                "tag_name": "v" + self.version,
                "draft": False,
                "prerelease": False,
                "assets": [
                    {"name": n, "browser_download_url": url + n} for n in (name, name + ".sha256")
                ],
            }
            self.write(output / "metadata.json", json.dumps(data).encode())
        elif stage == "download":
            self.write(output / "archive.tar.gz", b"independently verified payload")
            checksum = hashlib.sha256(b"independently verified payload").hexdigest()
            self.write(
                output / "archive.sha256",
                f"{checksum}  knx_to_openhab-{self.version}.tar.gz\n".encode(),
            )
        elif stage == "extract":
            assert (workspace / "verified.tar.gz").read_bytes() == b"independently verified payload"
            assert (workspace / "verified.tar.gz").stat().st_uid == 0
            assert candidate.name == self.version
            (candidate / "installer").mkdir(mode=0o700)
            os.chown(candidate / "installer", 65534, 65534)
            contract = {
                "updater_protocol": 9 if self.bad_contract else 1,
                "config_copy_protocol": 1,
                "accepted_input_schema_versions": [0],
                "output_schema_version": 1,
                "runtime_backward_compatible": True,
            }
            for name, raw in {
                "VERSION": self.version.encode(),
                "requirements.txt": b"",
                "installer/config_migrations.py": b"# never executed by root",
                "installer/update_contract.json": json.dumps(contract).encode(),
            }.items():
                self.write(candidate / name, raw)
        elif stage == "dependencies":
            (candidate / "venv").mkdir(mode=0o700)
            os.chown(candidate / "venv", 65534, 65534)
            self.write(candidate / "venv/runtime", str(candidate / "venv").encode())
        elif stage == "migrate":
            assert not (workspace / "secrets.env").exists()
            config = json.loads((workspace / "config-input.json").read_bytes())
            config["schema_version"] = 1
            config["new_default"] = True
            if self.bad_copy:
                config["sibling"] = "discarded"
            self.write(output / "config.json", json.dumps(config).encode())

    @staticmethod
    def write(path, raw):
        path.write_bytes(raw)
        path.chmod(0o600)
        os.chown(path, 65534, 65534)

    def service(self, action, name):
        assert name in SERVICES
        self.events.append((action, name))
        if action == "start" and name == SERVICES[0] and self.fail == "restart":
            self.fail = None
            raise RuntimeError("restart failure")
        if action in ("start", "stop"):
            self.active[name] = action == "start"
        else:
            self.enabled[name] = action == "enable"

    def notify_ready(self, timeout=30):
        return self.active[SERVICES[0]]


@pytest.fixture
def installation():
    if os.name != "posix" or os.geteuid() != 0:
        pytest.skip("isolated Linux root-private filesystem fixtures")
    from installer.update_core.transaction import ReleaseUpdater

    with tempfile.TemporaryDirectory(prefix="knxoh-transaction-", dir="/run") as tmp:
        root = Path(tmp)
        root.chmod(0o755)
        for name in ("app", "config", "data", "backups", "prepare"):
            (root / name).mkdir(mode=0o755)
        releases = root / "app/releases"
        releases.mkdir()
        (releases / "1.0.0").mkdir()
        (releases / "1.0.0/VERSION").write_bytes(b"1.0.0\n")
        (root / "app/current").symlink_to(releases / "1.0.0")
        paths = Paths(
            releases, root / "app/current", root / "config", root / "data", root / "backups"
        )
        (paths.config_dir / "config.json").write_bytes(
            b'{"sibling":{"preserved":[1,true]},"port":8085}\n'
        )
        (paths.config_dir / "config.json").chmod(0o640)
        os.chown(paths.config_dir / "config.json", 0, 65533)
        (paths.config_dir / "secrets.env").write_bytes(b"secret sentinel\n")
        (paths.config_dir / "secrets.env").chmod(0o640)
        os.chown(paths.config_dir / "secrets.env", 0, 65533)
        (paths.config_dir / "generator.json").write_bytes(b"generator sibling unchanged")
        (paths.config_dir / ".updater-mutation.lock").touch(mode=0o660)
        (paths.config_dir / ".updater-mutation.lock").chmod(0o660)
        os.chown(paths.config_dir / ".updater-mutation.lock", 0, 65533)
        for directory in (paths.data_dir, paths.backup_dir):
            os.chown(directory, 65533, 65533)
        (paths.data_dir / "update").mkdir(mode=0o700)
        os.chown(paths.data_dir / "update", 65533, 65533)
        for name in ("jobs", "sessions", "generated"):
            FakeSystemd.write(paths.data_dir / name, (name + " unchanged").encode())
            os.chown(paths.data_dir / name, 65533, 65533)
        FakeSystemd.write(paths.backup_dir / "sentinel", b"backup unchanged")
        os.chown(paths.backup_dir / "sentinel", 65533, 65533)
        request_id = str(uuid4())
        FakeSystemd.write(
            paths.data_dir / "update/request.json",
            json.dumps(
                {"format_version": 1, "request_id": request_id, "channel": "stable"}
            ).encode(),
        )
        os.chown(paths.data_dir / "update/request.json", 65533, 65533)
        adapter = FakeSystemd()

        def health(url, timeout):
            assert url == "http://127.0.0.1:8085/api/health"
            assert 0 < timeout <= 60
            target = paths.current.resolve().name
            if adapter.fail == "health" and target == "2.0.0" or adapter.fail_old:
                return {"status": "ready", "version": "wrong"}
            return {"status": "ready", "version": target}

        updater = ReleaseUpdater(
            paths,
            adapter,
            Limits(),
            lock_path=root / "lock",
            workspace_root=root / "prepare",
            worker_uid=65534,
            worker_gid=65534,
            service_uid=65533,
            http=health,
            readiness_timeout=0.01,
            drain_timeout=0.01,
        )
        yield updater, paths, adapter, request_id


def test_public_interface_exists():
    from installer.update_core.transaction import ReleaseUpdater, UpdateResult

    assert callable(ReleaseUpdater.run) and callable(ReleaseUpdater.recover)
    assert set(UpdateResult.__dataclass_fields__) == {
        "status",
        "version",
        "error",
        "rollback_status",
        "request_id",
    }


@pytest.mark.parametrize(
    "host, tls, expected",
    [
        ("0.0.0.0", False, "http://127.0.0.1:8085/api/health"),
        ("::", True, "https://[::1]:8085/api/health"),
        ("192.0.2.5", True, "https://192.0.2.5:8085/api/health"),
    ],
)
def test_local_health_endpoint(host, tls, expected):
    from installer.update_core.transaction import health_url

    assert health_url({"bind_host": host, "tls": tls}) == expected


def test_installed_entrypoint_interface():
    from installer.update_release import ReleaseUpdater, UpdateResult

    assert callable(ReleaseUpdater.run) and callable(UpdateResult)


def assert_sentinels(paths):
    assert (paths.config_dir / "secrets.env").read_bytes() == b"secret sentinel\n"
    assert (paths.config_dir / "generator.json").read_bytes() == b"generator sibling unchanged"
    assert (paths.backup_dir / "sentinel").read_bytes() == b"backup unchanged"
    for name in ("jobs", "sessions", "generated"):
        assert (paths.data_dir / name).read_bytes() == (name + " unchanged").encode()
        assert (paths.data_dir / name).stat().st_uid == 65533


def test_success_freezes_final_venv_and_commits_before_cleanup(installation):
    updater, paths, adapter, request_id = installation
    result = updater.run()
    assert result.status == "updated", result
    assert result.version == "2.0.0" and result.request_id == request_id
    assert result.error is None and result.rollback_status is None
    assert paths.current.resolve() == paths.releases / "2.0.0"
    assert (paths.releases / "2.0.0/venv/runtime").stat().st_uid == 0
    assert json.loads((paths.config_dir / "config.json").read_bytes())["sibling"] == {
        "preserved": [1, True]
    }
    assert StateStore(paths).load().phase == "committed"
    assert check_start_allowed(paths, "cleanup")
    assert not (paths.config_dir / ".updater-maintenance.json").exists()
    status = json.loads((paths.config_dir / ".updater-status.json").read_bytes())
    assert status["request_id"] == request_id
    assert adapter.active == dict.fromkeys(SERVICES, True)
    assert_sentinels(paths)


@pytest.mark.parametrize(
    "failure", ["metadata", "download", "extract", "dependencies", "migrate", "restart", "health"]
)
def test_failure_restores_pair_and_only_own_unpublished_candidate(installation, failure):
    updater, paths, adapter, _ = installation
    original = (paths.config_dir / "config.json").read_bytes()
    adapter.fail = failure
    result = updater.run()
    assert result.status == "failed", result
    assert result.error and result.rollback_status == "succeeded"
    assert paths.current.resolve() == paths.releases / "1.0.0"
    assert (paths.config_dir / "config.json").read_bytes() == original
    assert StateStore(paths).load().phase == "rolled-back"
    assert not (paths.config_dir / ".updater-maintenance.json").exists()
    if failure in ("metadata", "download", "extract", "dependencies", "migrate"):
        assert not (paths.releases / "2.0.0").exists()
    else:
        assert (paths.releases / "2.0.0").exists()  # publication is sticky
    assert_sentinels(paths)


@pytest.mark.parametrize(
    "kind",
    ["credentials", "space", "nofile", "contract", "sibling", "existing", "teardown", "path"],
)
def test_preflight_and_child_outputs_fail_closed(installation, monkeypatch, kind):
    updater, paths, adapter, _ = installation
    if kind == "credentials":
        (paths.config_dir / "config.json").write_bytes(b'{"auth":{"password":"never-copy"}}')
    elif kind == "space":
        monkeypatch.setattr("installer.update_core.transaction.available_bytes", lambda path: 0)
    elif kind == "nofile":
        monkeypatch.setattr(
            "installer.update_core.transaction.nofile_limits", lambda: (1024, 65536)
        )
    elif kind == "contract":
        adapter.bad_contract = True
    elif kind == "sibling":
        adapter.bad_copy = True
    elif kind == "existing":
        (paths.releases / "2.0.0").mkdir()
        (paths.releases / "2.0.0/evidence").write_bytes(b"do not touch")
    elif kind == "teardown":
        adapter.fail = "teardown"
    else:
        paths.releases.chmod(0o777)
    original = (paths.config_dir / "config.json").read_bytes()
    result = updater.run()
    assert result.status in ("failed", "blocked"), result
    assert paths.current.resolve() == paths.releases / "1.0.0"
    assert (paths.config_dir / "config.json").read_bytes() == original
    if kind == "credentials":
        assert not adapter.events
    if kind == "existing":
        assert (paths.releases / "2.0.0/evidence").read_bytes() == b"do not touch"
        assert result.rollback_status == "succeeded"
    if kind in ("space", "nofile", "contract"):
        assert kind in result.error.lower()
    assert_sentinels(paths)


def test_no_update_busy_and_sticky_replay(installation):
    from installer.update_core.state import LifecycleLock

    updater, paths, adapter, _ = installation
    with LifecycleLock(updater.lock_path).acquire():
        assert updater.run().status == "busy"
    adapter.version = "1.0.0"
    assert updater.run().status == "no-update"
    assert updater.run().status == "blocked"  # not another successful acknowledgement
    assert not (paths.releases / "2.0.0").exists()


def test_failed_rollback_keeps_gate_intent_and_blocks_request(installation):
    updater, paths, adapter, _ = installation
    adapter.fail = "health"
    adapter.fail_old = True
    result = updater.run()
    assert result.status == "failed" and result.error
    assert result.rollback_status.startswith("failed:")
    assert StateStore(paths).load().phase == "recovery-failed"
    assert (paths.config_dir / ".updater-maintenance.json").exists()
    assert not check_start_allowed(paths, "cleanup")
    assert updater.run().status == "blocked"
    status = json.loads((paths.config_dir / ".updater-status.json").read_bytes())
    assert status["phase"] == "recovery-failed"
    assert_sentinels(paths)


def test_active_mutation_times_out_without_stopping_services(installation):
    from installer.update_core.maintenance import mutation_lease

    updater, paths, adapter, _ = installation
    with mutation_lease(paths):
        result = updater.run()
    assert result.status == "failed" and result.rollback_status == "succeeded"
    assert not any(isinstance(event, tuple) for event in adapter.events)
    assert not (paths.config_dir / ".updater-maintenance.json").exists()


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "oversize", "unknown", "duplicate"])
def test_untrusted_request_is_descriptor_claimed_and_strict(installation, kind):
    updater, paths, adapter, request_id = installation
    path = paths.data_dir / "update/request.json"
    if kind == "symlink":
        path.unlink()
        path.symlink_to(paths.config_dir / "config.json")
    elif kind == "hardlink":
        os.link(path, paths.data_dir / "alias")
    elif kind == "oversize":
        path.write_bytes(b"x" * (Limits.REQUEST_BYTES + 1))
    elif kind == "unknown":
        path.write_bytes(
            json.dumps(
                {"format_version": 1, "request_id": request_id, "channel": "stable", "url": "evil"}
            ).encode()
        )
    else:
        path.write_bytes(b'{"format_version":1,"format_version":1}')
    assert updater.run().status == "blocked"
    assert not adapter.events


def test_readiness_never_exceeds_remaining_deadline(installation, monkeypatch):
    updater, paths, adapter, _ = installation
    times = iter([0.0, 0.0, 0.009, 0.01])
    monkeypatch.setattr("installer.update_core.transaction.time.monotonic", lambda: next(times))
    observed = []

    def notify(timeout):
        assert timeout <= 0.01
        return True

    adapter.notify_ready = notify
    updater.http = lambda url, timeout: observed.append(timeout) or {
        "status": "ready",
        "version": "1.0.0",
    }
    updater._ready("1.0.0")
    assert observed[0] <= 0.0011


def test_terminal_journal_target_mismatch_blocks_new_request(installation):
    updater, paths, adapter, _ = installation
    assert updater.run().status == "updated"
    paths.current.unlink()
    paths.current.symlink_to(paths.releases / "1.0.0")
    assert updater.check_clean_state().status == "blocked"
    assert updater.run().status == "blocked"


def test_preparation_refuses_hidden_workspace_and_bad_prior_tree(installation):
    updater, paths, adapter, _ = installation
    os.chown(paths.releases / "1.0.0/VERSION", 65533, 65533)
    result = updater.run()
    assert result.status == "blocked"
    assert not adapter.events


@pytest.mark.parametrize("when", ["before", "after"])
@pytest.mark.parametrize("operation", ["config", "link"])
def test_activation_filesystem_error_rolls_back_exact_bytes(
    installation, monkeypatch, when, operation
):
    from installer.update_core import secure_fs, transaction

    updater, paths, adapter, _ = installation
    original = (paths.config_dir / "config.json").read_bytes()
    failed = False
    function = secure_fs.atomic_write if operation == "config" else transaction.os.replace

    def fault(*args, **kwargs):
        nonlocal failed
        selected = (
            args[0] == paths.config_dir / "config.json"
            if operation == "config"
            else args[1] == "current"
        )
        if selected and not failed:
            failed = True
            if when == "after":
                function(*args, **kwargs)
            raise OSError("injected activation failure")
        return function(*args, **kwargs)

    if operation == "config":
        monkeypatch.setattr(secure_fs, "atomic_write", fault)
    else:
        monkeypatch.setattr(transaction.os, "replace", fault)
    result = updater.run()
    assert failed and result.rollback_status == "succeeded", result
    assert paths.current.resolve() == paths.releases / "1.0.0"
    assert (paths.config_dir / "config.json").read_bytes() == original
    assert_sentinels(paths)


@pytest.mark.parametrize("kind", ["world-readable", "legacy-plaintext"])
def test_unsafe_external_credentials_refused_before_child(installation, kind):
    updater, paths, adapter, _ = installation
    secret = paths.config_dir / "secrets.env"
    if kind == "world-readable":
        secret.chmod(0o644)
    else:
        secret.write_bytes(b"KNXOH_UI_PASSWORD_B64=cGxhaW50ZXh0\n")
    assert updater.run().status == "blocked"
    assert not adapter.events


def test_cleanup_guard_denied_during_copied_migration(installation):
    updater, paths, adapter, _ = installation
    run = adapter.run_child

    def child(stage, *args):
        if stage == "migrate":
            assert not check_start_allowed(paths, "cleanup")
            assert not check_start_allowed(paths, "ui")
        return run(stage, *args)

    adapter.run_child = child
    assert updater.run().status == "updated"


def test_service_umask_does_not_remove_worker_traversal(installation):
    updater, paths, adapter, _ = installation
    previous = os.umask(0o077)
    try:
        result = updater.run()
    finally:
        os.umask(previous)
    assert result.status == "updated", result


@pytest.mark.parametrize("kind", ["installer-marker", "version-mismatch", "input-schema"])
def test_actual_installer_and_schema_contract_preflight(installation, kind):
    updater, paths, adapter, _ = installation
    if kind == "installer-marker":
        (paths.releases / "1.0.0/.install-incomplete").touch()
    elif kind == "version-mismatch":
        (paths.releases / "1.0.0/VERSION").write_bytes(b"9.0.0")
    else:
        (paths.config_dir / "config.json").write_bytes(b'{"schema_version":99}')
    result = updater.run()
    assert result.status in ("blocked", "failed")
    assert "migrate" not in adapter.events


def test_http_operation_cannot_extend_readiness_deadline(installation):
    import threading
    import time

    updater, paths, adapter, _ = installation
    release = threading.Event()
    updater.http = lambda *args: release.wait(0.3)
    started = time.monotonic()
    try:
        with pytest.raises(TimeoutError):
            updater._ready("1.0.0")
        assert time.monotonic() - started < 0.15
    finally:
        release.set()


@pytest.mark.parametrize("fault", ["duplicate", "shell", "service-owner"])
def test_protected_path_contract_is_data_not_shell(installation, fault):
    from installer.update_core.transaction import load_paths

    updater, paths, adapter, _ = installation
    path = paths.config_dir / "paths.env"
    lines = [
        f'{name}="{value}"'
        for name, value in zip(
            ("KNXOH_INSTALL_DIR", "KNXOH_CONFIG_DIR", "KNXOH_DATA_DIR", "KNXOH_BACKUP_DIR"),
            (paths.releases.parent, paths.config_dir, paths.data_dir, paths.backup_dir),
        )
    ]
    path.write_text("\n".join(lines))
    assert load_paths(path) == paths
    if fault == "duplicate":
        path.write_text("\n".join([*lines, lines[0]]))
    elif fault == "shell":
        path.write_text("\n".join(lines).replace(str(paths.releases.parent), "$(id)"))
    else:
        os.chown(path, 65533, 65533)
    with pytest.raises((ValueError, OSError)):
        load_paths(path)


def test_rollback_restores_cleanup_after_ui_wants_dependency(installation):
    updater, paths, adapter, _ = installation
    adapter.active["knxohui-backup-cleanup.service"] = False
    adapter.active["knxohui-backup-cleanup.timer"] = False
    adapter.enabled["knxohui-backup-cleanup.timer"] = False
    expected_active, expected_enabled = adapter.active.copy(), adapter.enabled.copy()
    service = adapter.service

    def wants(action, name):
        service(action, name)
        if action == "start" and name == "knxohui.service":
            adapter.active["knxohui-backup-cleanup.timer"] = True

    adapter.service = wants
    adapter.fail = "migrate"
    result = updater.run()
    assert result.rollback_status == "succeeded", result
    assert adapter.active == expected_active
    assert adapter.enabled == expected_enabled


def test_fixed_production_service_adapter_allowlist_and_notify_deadline():
    from types import SimpleNamespace

    from installer.update_core.systemd import SystemdAdapter

    calls = []

    def runner(argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(stdout="Type=notify\nActiveState=active\nSubState=running\n")

    adapter = SystemdAdapter(str(uuid4()), runner=runner)
    adapter.service("start", "knxohui.service")
    assert calls[0][0] == ["/usr/bin/systemctl", "start", "--no-block", "--", "knxohui.service"]
    assert adapter.notify_ready(timeout=0.05)
    assert calls[-1][1]["timeout"] == 0.05
    count = len(calls)
    with pytest.raises(ValueError):
        adapter.service("restart", "untrusted.service")
    assert len(calls) == count
    adapter.stopped.add("metadata")
    adapter.bind_request(str(uuid4()))
    assert not adapter.stopped


@pytest.mark.parametrize("when", ["before", "after"])
def test_reservation_uses_durable_not_in_memory_provenance(installation, monkeypatch, when):
    updater, paths, adapter, _ = installation
    save = StateStore.save
    failed = False

    def fail_identity(store, journal):
        nonlocal failed
        if journal.candidate_created and not failed:
            failed = True
            if when == "after":
                save(store, journal)
            raise OSError("reservation journal persistence failed")
        return save(store, journal)

    monkeypatch.setattr(StateStore, "save", fail_identity)
    result = updater.run()
    assert failed
    assert "extract" not in adapter.events
    candidate = paths.releases / "2.0.0"
    if when == "before":
        assert result.rollback_status.startswith("failed:"), result
        assert candidate.is_dir() and candidate.stat().st_uid == 0
        assert StateStore(paths).load().candidate_created is False
    else:
        assert result.rollback_status == "succeeded", result
        assert not candidate.exists()


@pytest.mark.parametrize("when", ["before", "after"])
def test_commit_sync_error_never_rolls_back_a_durable_commit(installation, monkeypatch, when):
    updater, paths, adapter, _ = installation
    save = StateStore.save
    failed = False

    def fail_commit(store, journal):
        nonlocal failed
        if journal.phase == "committed" and not failed:
            failed = True
            if when == "after":
                save(store, journal)
            raise OSError("commit sync error")
        return save(store, journal)

    monkeypatch.setattr(StateStore, "save", fail_commit)
    result = updater.run()
    assert failed
    if when == "after":
        assert paths.current.resolve().name == "2.0.0"
        assert StateStore(paths).load().phase == "committed"
        assert (paths.config_dir / ".updater-maintenance.json").exists()
        assert updater.recover("boot").status == "clean"
    else:
        assert result.rollback_status == "succeeded", result
        assert paths.current.resolve().name == "1.0.0"


def test_real_preparation_identity_can_read_only_selected_workspace(installation):
    import subprocess

    updater, paths, adapter, _ = installation
    child = adapter.run_child
    probe = """
import pathlib, sys
p = pathlib.Path(sys.argv[1])
assert (p / 'input.json').read_bytes()
if (p / 'config-input.json').exists():
    assert (p / 'config-input.json').read_bytes()
try:
    (p / 'input.json').write_bytes(b'forbidden')
except PermissionError:
    pass
else:
    raise AssertionError('child changed protected input')
(p / 'output/probe').write_bytes(b'child output')
"""

    def run(stage, paths, workspace, candidate):
        subprocess.run(
            ["/usr/bin/python3", "-I", "-c", probe, str(workspace)],
            user=65534,
            group=65534,
            extra_groups=[],
            cwd="/",
            env={"PATH": "/usr/bin:/bin"},
            check=True,
            timeout=10,
            capture_output=True,
        )
        return child(stage, paths, workspace, candidate)

    adapter.run_child = run
    result = updater.run()
    assert result.status == "updated", result
    assert_sentinels(paths)


@pytest.mark.parametrize(
    "key", ["KNXOH_UI_PASSWORD_HASH_B64", "session_secret_b64", "access_token_b64"]
)
def test_encoded_embedded_credentials_are_not_copied(installation, key):
    updater, paths, adapter, _ = installation
    (paths.config_dir / "config.json").write_bytes(
        json.dumps({"auth": {key: "sensitive"}}).encode()
    )
    assert updater.run().status == "blocked"
    assert not adapter.events
