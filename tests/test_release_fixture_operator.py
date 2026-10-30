"""Guard/phase tests do not dispatch WSL or perform privileged preparation."""

import ast
import subprocess
import sys
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest


def api():
    from scripts import release_fixture_operator

    return release_fixture_operator


def test_exact_phases_and_separate_authorization():
    assert api().PHASES == (
        "prepare-fixture",
        "stable-update",
        "no-update",
        "checksum-rejection",
        "migration-rejection",
        "retry",
    )
    for phase in api().PHASES:
        with pytest.raises(ValueError):
            api().authorize(
                phase, "prepare-fixture" if phase != "prepare-fixture" else "stable-update"
            )
        api().authorize(phase, phase)
    for phase in ("boot", "repair", "reset", "cleanup", "adopt", "force", "tls-only"):
        with pytest.raises(ValueError):
            api().authorize(phase, phase)


def test_hosts_adds_only_five_names_preserves_original():
    original = b"127.0.0.1 localhost\n::1 localhost ip6-localhost\n# original\n"
    changed = api().hosts_bytes(original)
    assert changed.startswith(original)
    for name in api().HOSTS:
        assert changed.split().count(name.encode()) == 1
    with pytest.raises(ValueError):
        api().hosts_bytes(changed)
    with pytest.raises(ValueError):
        api().hosts_bytes(b"10.0.0.1 pypi.org\n")


@pytest.mark.parametrize(
    "phase,previous,current",
    [
        ("stable-update", None, "0.1.0"),
        ("no-update", "stable-update", "0.1.1"),
        ("checksum-rejection", "no-update", "0.1.1"),
        ("migration-rejection", "checksum-rejection", "0.1.1"),
        ("retry", "migration-rejection", "0.1.1"),
    ],
)
def test_fixed_phase_sequence(phase, previous, current):
    api().check_sequence(phase, previous, current)
    with pytest.raises(ValueError):
        api().check_sequence(phase, previous, "9.9.9")
    with pytest.raises(ValueError):
        api().check_sequence(phase, "unknown", current)


def test_matching_ack_and_terminal_journal_not_public_status_only():
    request = "11111111-1111-4111-8111-111111111111"
    journal = dict(request_id=request, phase="committed", channel="stable")
    status = dict(request_id=request, phase="committed")
    assert api().terminal("stable-update", request, journal, status) is True
    assert (
        api().terminal(
            "checksum-rejection",
            request,
            {**journal, "phase": "rolled-back"},
            {**status, "phase": "rolled-back"},
        )
        is True
    )
    assert (
        api().terminal(
            "stable-update",
            request,
            {**journal, "phase": "preparing"},
            {**status, "phase": "preparing"},
        )
        is False
    )
    with pytest.raises(ValueError):
        api().terminal("stable-update", request, {**journal, "request_id": "other"}, status)
    with pytest.raises(ValueError):
        api().terminal(
            "stable-update",
            request,
            {**journal, "phase": "rolled-back"},
            {**status, "phase": "rolled-back"},
        )


def test_login_form_token_strict_extraction():
    assert (
        api().login_token('<input type="hidden" name="csrf_token" value="test-token">')
        == "test-token"
    )
    for text in ("", '<input name="csrf_token" value="a"><input name="csrf_token" value="b">'):
        with pytest.raises(ValueError):
            api().login_token(text)


def test_cli_has_no_host_or_runtime_override_and_refuses_without_authorization(tmp_path):
    for args in (
        ["--phase", "prepare-fixture"],
        ["--phase", "boot"],
        ["--host", "Ubuntu"],
        ["--force"],
    ):
        result = subprocess.run(
            [sys.executable, "-B", "-m", "scripts.release_fixture_operator", *args],
            capture_output=True,
            text=True,
        )
        assert result.returncode != 0
    assert list(tmp_path.iterdir()) == []


def test_guarded_payload_has_no_candidate_import_or_direct_coordinator():
    payload = api().guest_payload("prepare-fixture", {}, {}, "nonce", {}, {}, {})
    compile(payload, "<fixture operator test>", "exec")
    assert "refuse_cached_modules(sys.modules)" in payload
    assert "verify_tree(approval)" in payload
    assert "harness._check_virtualization('systemd-nspawn',nonce)" in payload
    assert "collect_installed(" not in payload
    assert "Coordinator(" not in payload
    tree = ast.parse(payload)
    assert not any(
        isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "run_probe"
        for n in ast.walk(tree)
    )


def test_real_cookie_login_csrf_and_empty_default_stable_post(monkeypatch):
    calls = []

    class Application(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            self.send_response(200)
            if self.path == "/login":
                self.send_header("Set-Cookie", "knx_login_csrf=test-token; Path=/")
                self.end_headers()
                self.wfile.write(b'<input name="csrf_token" value="test-token">')
            else:
                self.end_headers()
                self.wfile.write(b"authenticated")

        def do_POST(self):
            body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            calls.append((self.path, body, dict(self.headers)))
            if self.path == "/login":
                values = urllib.parse.parse_qs(body.decode())
                assert values == dict(
                    username=["acceptance"], password=["test-secret"], csrf_token=["test-token"]
                )
                assert "knx_login_csrf=test-token" in self.headers["Cookie"]
                self.send_response(302)
                self.send_header("Location", "/")
                self.send_header("Set-Cookie", "knx_session=session; Path=/")
                self.send_header("Set-Cookie", "knx_csrf=csrf; Path=/")
                self.end_headers()
            else:
                assert self.path == "/api/version/update"
                self.send_response(409)
                self.end_headers()
                self.wfile.write(b'{"error":"test endpoint only"}')

    # No app/updater simulation is claimed: this tests the HTTP auth client
    # against an independent protocol endpoint, not actual installed acceptance.
    server = ThreadingHTTPServer(("127.0.0.1", 0), Application)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    original = api().urllib.request.build_opener

    class LocalOpener:
        def __init__(self):
            self.inner = None

        def open(self, request, timeout):
            request.full_url = request.full_url.replace(":8085", ":" + str(server.server_port))
            return self.inner.open(request, timeout=timeout)

    def local(*handlers):
        opener = LocalOpener()
        opener.inner = original(*handlers)
        return opener

    monkeypatch.setattr(api().urllib.request, "build_opener", local)
    try:
        client = api().AuthenticatedAPI(dict(user="acceptance", password="test-secret"))
        assert client.submit()[0] == 409
        path, body, headers = calls[-1]
        assert path == "/api/version/update" and body == b""
        assert "Content-Type" not in headers
        assert headers["X-Csrf-Token"] == "csrf"
        assert "knx_session=session" in headers["Cookie"]
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def guest(monkeypatch):
    import importlib

    monkeypatch.setitem(sys.modules, "fixture_operator", api())
    return importlib.import_module("scripts.release_fixture_guest")


def test_prepare_refuses_unknown_state_before_any_effect(tmp_path, monkeypatch):
    module = guest(monkeypatch)
    monkeypatch.setattr(module, "CONTROL", tmp_path)
    with pytest.raises(ValueError, match="Unknown existing fixture"):
        module.prepare({}, {})
    assert list(tmp_path.iterdir()) == []


def test_foreign_host_bind_and_wrong_root_mount_refused(monkeypatch):
    module = guest(monkeypatch)
    root = "100 1 8:64 /var/lib/machines/knxoh-acceptance / rw,relatime - ext4 /dev/sde rw\n"
    from pathlib import Path

    monkeypatch.setattr(Path, "read_text", lambda *_a, **_kw: root)
    module.private_effect_mounts()
    for raw in (
        root + "101 100 8:64 /etc/hosts /etc/hosts rw - ext4 /dev/sde rw\n",
        root.replace("/var/lib/machines/knxoh-acceptance", "/"),
        root + "101 100 8:64 /etc /etc rw - ext4 /dev/sde rw\n",
    ):
        monkeypatch.setattr(Path, "read_text", lambda *_a, **_kw: raw)
        with pytest.raises(ValueError):
            module.private_effect_mounts()


def test_no_update_cannot_accept_generic_rollback_failure():
    request = "11111111-1111-4111-8111-111111111111"
    root = dict(request_id=request, phase="rolled-back", channel="stable")
    with pytest.raises(ValueError):
        api().terminal(
            "no-update",
            request,
            root,
            dict(
                request_id=request,
                phase="rolled-back",
                message="Update failed; previous release preserved",
            ),
        )
    assert api().terminal(
        "no-update",
        request,
        root,
        dict(request_id=request, phase="rolled-back", message="No newer compatible release"),
    )


def test_negative_stage_requires_real_expected_success_or_failure(monkeypatch):
    module = guest(monkeypatch)
    success = dict(Result="success", ExecMainStatus="0")
    failed = dict(Result="exit-code", ExecMainStatus="1")
    module.check_stage_result("stable-update", "dependencies", success)
    module.check_stage_result("migration-rejection", "migrate", failed)
    with pytest.raises(ValueError):
        module.check_stage_result("checksum-rejection", "download", failed)
    with pytest.raises(ValueError):
        module.check_stage_result("migration-rejection", "migrate", success)


def test_current_link_is_original_absolute_production_form(tmp_path, monkeypatch):
    module = guest(monkeypatch)
    current = tmp_path / "current"
    expected = tmp_path / "releases/0.1.1"
    try:
        current.symlink_to(expected, target_is_directory=True)
    except OSError:
        pytest.skip("Native symlink privilege unavailable")
    module.check_current_link(tmp_path, "0.1.1")
    current.unlink()
    current.symlink_to("releases/0.1.1", target_is_directory=True)
    with pytest.raises(ValueError):
        module.check_current_link(tmp_path, "0.1.1")


def test_original_wheel_receipt_cannot_be_replaced_by_observed_new_bytes():
    original = [dict(name="one.whl", size=10, sha256="a" * 64)]
    manifest = dict(
        wheels=[dict(name="one.whl", size=10, sha256="a" * 64, project="one", version="1")]
    )
    api().check_original_wheels(manifest, original)
    manifest["wheels"][0]["sha256"] = "b" * 64
    with pytest.raises(ValueError):
        api().check_original_wheels(manifest, original)


def test_parent_inventory_allows_only_exact_own_transaction_names(monkeypatch):
    module = guest(monkeypatch)
    original = dict(children=["0.1.0", "acceptance-known"], links=4, uid=0, inode=123)
    actual = dict(children=["0.1.0", "0.1.1", "acceptance-known"], links=5, uid=0, inode=123)
    module.check_parent_inventory(actual, original, {"0.1.1"})
    for changed in (
        {**actual, "children": [*actual["children"], "unknown"]},
        {**actual, "inode": 999},
        {**actual, "links": 6},
    ):
        with pytest.raises(ValueError):
            module.check_parent_inventory(changed, original, {"0.1.1"})


def test_service_request_uses_original_protocol_before_uuid_path_use(tmp_path, monkeypatch):
    import stat
    from pathlib import Path
    from types import SimpleNamespace

    module = guest(monkeypatch)
    monkeypatch.setattr(module, "state", SimpleNamespace(DATA=tmp_path))
    monkeypatch.setattr(
        Path,
        "lstat",
        lambda *_a, **_kw: SimpleNamespace(st_mode=stat.S_IFDIR | 0o700, st_uid=999, st_gid=989),
    )
    monkeypatch.setattr(
        module,
        "worker_read",
        lambda *_a, **_kw: b'{"format_version":1,"channel":"stable","request_id":"../outside"}',
    )
    with pytest.raises(ValueError):
        module.read_request()


def test_system_tls_query_uses_actual_seed_default_session_without_cache_overrides(monkeypatch):
    module = guest(monkeypatch)
    query = next(
        c
        for c in module.tls_proof.__code__.co_consts
        if isinstance(c, str) and "import sys,ssl,ensurepip" in c
    )
    calls = [
        node
        for node in ast.walk(ast.parse(query))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "PipSession"
    ]
    assert len(calls) == 1 and calls[0].args == [] and calls[0].keywords == []
    assert "session.verify is True" in query
    assert "ssl.SSLCertVerificationError" in query and "except SSLError" in query


@pytest.mark.parametrize(
    "foreign",
    [
        "/usr/local/sbin/knxoh-foreign",
        "/usr/local/libexec/.knxohui-bundle-foreign",
        "/opt/knx_to_openhab",
        "/etc/systemd/system/knxoh-foreign.service",
    ],
)
def test_full_collected_keyset_refuses_unknown_original_absence(monkeypatch, foreign):
    module = guest(monkeypatch)
    original = {"/known": dict(kind="file", inode=1, sha256="a")}
    actual = {**original, foreign: dict(kind="file", inode=2, sha256="b")}
    with pytest.raises(ValueError):
        module.check_collected_entries(actual, original)
    with pytest.raises(ValueError):
        module.check_collected_entries({}, original)
    module.check_collected_entries(original, original)


@pytest.mark.parametrize(
    "foreign", ["archive-foreign.tar.gz", "snapshot-foreign.json", "journal.json"]
)
def test_protected_state_original_empty_children_refused_before_prepare(
    monkeypatch, tmp_path, foreign
):
    from types import ModuleType, SimpleNamespace

    module = guest(monkeypatch)
    import scripts.nested_fixture_state as paths

    original = {
        str(paths.CONFIG / ".updater-state"): dict(kind="directory", children=[], inode=1, links=2)
    }
    actual = {name: {**value, "children": [foreign]} for name, value in original.items()}
    state = ModuleType("test_state")
    state.__dict__.update(vars(paths))
    state.collect_inventory = lambda **_: dict(entries=actual)
    monkeypatch.setattr(module, "state", state)
    for name in ("fs", "repair", "fixture", "admin"):
        monkeypatch.setattr(module, name, ModuleType(name))
    module.repair.inventory_entry = lambda *_a, **_kw: None
    monkeypatch.setattr(module, "CONTROL", tmp_path / "absent-control")
    monkeypatch.setattr(module, "os", SimpleNamespace(name="posix", geteuid=lambda: 0))
    for name in ("private_effect_mounts", "no_outbound", "runtime_identity"):
        monkeypatch.setattr(module, name, lambda: None)
    writers = []
    monkeypatch.setattr(module, "prepare", lambda *_: writers.append("prepare"))
    baseline = dict(DIRECT_OBSERVATIONS=dict(footprint=dict(entries=original)))
    with pytest.raises(ValueError):
        module.run("prepare-fixture", baseline, {}, {})
    assert writers == [] and not (tmp_path / "absent-control").exists()


def transaction_records():
    """Synthetic protocol1 records, never historical or actual runtime evidence."""
    from scripts.nested_fixture_state import BASE

    requests = ["11111111-1111-4111-8111-111111111111", "22222222-2222-4222-8222-222222222222"]
    root = dict(
        candidate=str(BASE / "releases/0.1.1"),
        prior_target=str(BASE / "releases/0.1.0"),
        candidate_identity=[1, 2],
        candidate_uid=997,
        candidate_created=True,
        candidate_published=True,
        format_version=1,
        request_id=requests[0],
        channel="stable",
        phase="committed",
        snapshot_allowlist=["config.json"],
        service_states={
            name: dict(
                active=name != "knxohui-backup-cleanup.service",
                enabled=name != "knxohui-backup-cleanup.service",
            )
            for name in (
                "knxohui.service",
                "knxohui-backup-cleanup.service",
                "knxohui-backup-cleanup.timer",
            )
        },
        seen_request_ids=requests[:1],
    )
    return [dict(phase="stable-update", root=root)], requests


@pytest.mark.skipif(
    sys.platform == "win32", reason="Original journal decoder requires POSIX absolute paths"
)
def test_transaction_allowances_require_original_decoder_exact_ledger_and_phase(monkeypatch):
    import copy

    module = guest(monkeypatch)
    records, requests = transaction_records()
    module.validate_own_transactions(records, records[-1]["root"])
    for change in (
        "noncanonical",
        "unrelated-ledger",
        "wrong-phase",
        "boolean-flag",
        "no-update-archive",
    ):
        bad = copy.deepcopy(records)
        if change == "noncanonical":
            bad[0]["root"]["request_id"] = "../foreign"
        elif change == "unrelated-ledger":
            bad[0]["root"]["seen_request_ids"].append(requests[1])
        elif change == "wrong-phase":
            bad[0]["phase"] = "retry"
        elif change == "boolean-flag":
            bad[0]["root"]["candidate_created"] = 1
        else:
            bad.append(
                dict(
                    phase="no-update",
                    root={
                        **bad[0]["root"],
                        "request_id": requests[1],
                        "seen_request_ids": requests,
                        "phase": "rolled-back",
                    },
                )
            )
        with pytest.raises(ValueError):
            module.validate_own_transactions(bad, bad[-1]["root"])


def test_dispatch_timeout_retains_exact_partial_bytes_unknown_status_no_retry(
    tmp_path, monkeypatch
):
    calls = []

    def timeout(*args, **kwargs):
        calls.append(kwargs["timeout"])
        raise subprocess.TimeoutExpired(
            "wsl.exe", 1800, output=b'{"event":"REQUEST"}\n\xff', stderr=b"partial\xfe"
        )

    monkeypatch.setattr(api().subprocess, "run", timeout)
    assert api().dispatch(["wsl.exe"], "not-saved-payload", tmp_path, "stable-update") != 0
    assert calls == [1800]
    assert (tmp_path / "observations.jsonl").read_bytes() == b'{"event":"REQUEST"}\n\xff'
    assert (tmp_path / "stderr.log").read_bytes() == b"partial\xfe"
    assert "unknown" in (tmp_path / "exit.txt").read_text()
    assert "timed-out" in (tmp_path / "exit.txt").read_text()
    assert "stable-update" in (tmp_path / "dispatch-outcome.json").read_text()
    assert "not-saved-payload" not in "".join(
        p.read_text(errors="replace") for p in tmp_path.iterdir()
    )


def test_dispatch_launch_failure_records_phase_unknown_and_does_not_retry(tmp_path, monkeypatch):
    calls = []

    def launch(*args, **kwargs):
        calls.append(1)
        raise OSError("transport unavailable")

    monkeypatch.setattr(api().subprocess, "run", launch)
    assert api().dispatch(["wsl.exe"], "private-payload", tmp_path, "prepare-fixture") != 0
    assert calls == [1]
    assert "launch-failed" in (tmp_path / "exit.txt").read_text()
    assert "prepare-fixture" in (tmp_path / "dispatch-outcome.json").read_text()


def test_retained_membership_rejects_receipt_with_no_exact_shape(monkeypatch):
    module = guest(monkeypatch)
    with pytest.raises(ValueError):
        module.preserve_retained(dict(request="5c4f51f8-2bdf-4e2e-ac71-cfb3897397b0", metadata={}))


@pytest.fixture(
    params=["5c4f51f8-2bdf-4e2e-ac71-cfb3897397b0", "dd13accd-c549-467c-b26d-4c2c25a797db"]
)
def retained_tree(tmp_path, monkeypatch, request):
    import os
    from types import SimpleNamespace

    if sys.platform == "win32" or os.geteuid() != 0:
        pytest.skip("Real root-private no-follow/worker-owner test requires Linux root")
    module = guest(monkeypatch)
    from installer.update_core import secure_fs

    monkeypatch.setattr(module, "fs", secure_fs)
    base, prep_root = tmp_path / "app", tmp_path / "prep"
    monkeypatch.setattr(module, "state", SimpleNamespace(BASE=base, PREPARATION=prep_root))
    request = request.param
    candidate, prep = base / "releases" / ("acceptance-" + request), prep_root / (
        "acceptance-" + request
    )
    output = prep / "migrate/output"
    (candidate / "installer").mkdir(parents=True, mode=0o755)
    output.mkdir(parents=True, mode=0o700)
    (candidate / "installer/config_migrations.py").write_bytes(b"# original retained test script\n")
    (prep / "migrate/input.json").write_bytes(b"{}")
    (output / "probe.json").write_bytes(b'{"uid":997}')
    (output / "heartbeat").write_bytes(b"heartbeat")
    for path in (candidate, candidate / "installer"):
        path.chmod(0o755)
    for path in (prep, prep / "migrate"):
        os.chown(path, 0, 988)
        path.chmod(0o750)
    os.chown(output, 997, 988)
    for path in output.iterdir():
        os.chown(path, 997, 988)
        path.chmod(0o600)
    os.chown(prep / "migrate/input.json", 0, 988)
    (prep / "migrate/input.json").chmod(0o440)
    members = [
        candidate,
        candidate / "installer",
        candidate / "installer/config_migrations.py",
        prep,
        prep / "migrate",
        prep / "migrate/input.json",
        output,
        output / "heartbeat",
        output / "probe.json",
    ]
    expected = dict(
        request=request,
        metadata={str(p): module.metadata(p.lstat()) for p in members},
        candidate_script_sha256=module.digest(
            (candidate / "installer/config_migrations.py").read_bytes()
        ),
        heartbeat_sha256=module.digest((output / "heartbeat").read_bytes()),
        probe_sha256=module.digest((output / "probe.json").read_bytes()),
    )
    monkeypatch.setattr(
        module, "show", lambda *_: dict(MainPID="0", ControlPID="0", ControlGroup="")
    )
    return module, expected, output


def test_genuine_retained_tree_has_exact_membership_but_no_input_content_proof(retained_tree):
    module, expected, output = retained_tree
    proof = module.preserve_retained(expected)
    assert proof["input_content_pinned"] is False
    # Original receipt pins only input stat metadata, not content. Same-length
    # changes must not be presented as a failed/original content-hash proof.
    source = output.parent / "input.json"
    source.write_bytes(b"[]")
    assert module.preserve_retained(expected)["input_content_pinned"] is False


@pytest.mark.parametrize("extra", ["file", "directory", "symlink", "fifo"])
def test_retained_output_rejects_extra_names_even_with_same_ext4_directory_metadata(
    retained_tree, monkeypatch, extra
):
    import os

    module, expected, output = retained_tree
    foreign = output / "foreign"
    if extra == "file":
        foreign.write_bytes(b"extra")
    elif extra == "directory":
        foreign.mkdir()
    elif extra == "symlink":
        foreign.symlink_to(output / "probe.json")
    else:
        os.mkfifo(foreign)
    original_metadata = module.metadata
    old = expected["metadata"][str(output)]

    def unchanged_block(info):
        value = original_metadata(info)
        if value["inode"] == old["inode"]:
            value = {**value, "size": old["size"], "links": old["links"]}
        return value

    monkeypatch.setattr(module, "metadata", unchanged_block)
    assert module.metadata(output.lstat()) == old
    before = sorted(p.name for p in output.iterdir())
    with pytest.raises(ValueError, match="membership"):
        module.preserve_retained(expected)
    assert sorted(p.name for p in output.iterdir()) == before


def test_negative_marker_attribution_checks_uid_source_and_actual_helper_parent(monkeypatch):
    module = guest(monkeypatch)
    marker = dict(
        fixture="copied-cli-migration-rejection-v1",
        uid=997,
        gid=988,
        pid=1235,
        parent_pid=1234,
        co_filename="/candidate/installer/config_migrations.py",
        script_sha256="a" * 64,
        intended_exit=73,
    )
    module.check_migration_marker(
        marker, "/candidate/installer/config_migrations.py", "a" * 64, 1234
    )
    for changed in (
        {**marker, "uid": 0},
        {**marker, "parent_pid": 9999},
        {**marker, "co_filename": "/other.py"},
        {**marker, "script_sha256": "b" * 64},
        {**marker, "intended_exit": 1},
    ):
        with pytest.raises(ValueError):
            module.check_migration_marker(
                changed, "/candidate/installer/config_migrations.py", "a" * 64, 1234
            )
    with pytest.raises(ValueError):
        module.check_stage_result(
            "migration-rejection", "migrate", dict(Result="exit-code", ExecMainStatus="73")
        )


@pytest.fixture
def admitted_transaction_tree(tmp_path, monkeypatch):
    import base64
    import json
    import os
    from types import SimpleNamespace

    if sys.platform == "win32" or os.geteuid() != 0:
        pytest.skip(
            "Original secure filesystem and journal decoder require private Linux root tests"
        )
    module = guest(monkeypatch)
    from installer.update_core import secure_fs
    from installer.update_core.protocol import Paths
    from scripts import nested_fixture_repair as repair
    from scripts import nested_fixture_state as paths

    for key, name in (
        ("BASE", "app"),
        ("CONFIG", "config"),
        ("DATA", "data"),
        ("BACKUPS", "backups"),
        ("PREPARATION", "preparation"),
    ):
        path = tmp_path / name
        path.mkdir(mode=0o700)
        monkeypatch.setattr(paths, key, path)
    monkeypatch.setattr(module, "state", paths)
    monkeypatch.setattr(module, "repair", repair)
    monkeypatch.setattr(module, "fs", secure_fs)
    monkeypatch.setattr(
        module,
        "fixture",
        SimpleNamespace(
            expected_paths=lambda: Paths(
                paths.BASE / "releases",
                paths.BASE / "current",
                paths.CONFIG,
                paths.DATA,
                paths.BACKUPS,
            )
        ),
    )
    control, unit, hosts = tmp_path / "control", tmp_path / "unit.service", tmp_path / "hosts"
    control.mkdir(mode=0o700)
    monkeypatch.setattr(module, "CONTROL", control)
    monkeypatch.setattr(module, "UNIT", unit)
    monkeypatch.setattr(module, "JOURNAL", paths.CONFIG / ".updater-state/journal.json")
    (paths.BASE / "releases").mkdir()
    (paths.BASE / "releases/0.1.0").mkdir()
    (paths.BASE / "current").symlink_to(paths.BASE / "releases/0.1.0", target_is_directory=True)
    (paths.CONFIG / ".updater-state").mkdir(mode=0o700)
    original_config = b'{"schema_version":1,"kept":true}'
    for name, raw in (
        ("config.json", original_config),
        (".updater-log.txt", b"old"),
        (".updater-status.json", b"{}"),
    ):
        (paths.CONFIG / name).write_bytes(raw)
    hosts.write_bytes(b"127.0.0.1 localhost\n")
    listed = [
        paths.BASE,
        paths.BASE / "releases",
        paths.BASE / "current",
        paths.CONFIG,
        paths.CONFIG / ".updater-state",
        paths.CONFIG / "config.json",
        paths.CONFIG / ".updater-log.txt",
        paths.CONFIG / ".updater-status.json",
        paths.DATA,
        paths.PREPARATION,
    ]
    original = {str(p): repair.inventory_entry(p, details=True) for p in listed}
    original["/etc/hosts"] = repair.inventory_entry(hosts, details=True)
    baseline = dict(DIRECT_OBSERVATIONS=dict(footprint=dict(entries=original)))
    for name, raw in (
        ("hosts.original", hosts.read_bytes()),
        ("hosts.installed", module.hosts_bytes(hosts.read_bytes())),
        ("config.original", original_config),
    ):
        (control / name).write_bytes(raw)
    hosts.write_bytes((control / "hosts.installed").read_bytes())
    unit.write_bytes(module.unit_bytes())
    unit.chmod(0o644)
    (control / "prepare-fixture.result.json").write_text(
        json.dumps(
            dict(
                phase="prepare-fixture",
                system_tls=True,
                unit_entry=repair.inventory_entry(unit, details=True),
            )
        )
    )
    records, _ = transaction_records()
    root = records[0]["root"]
    request = root["request_id"]
    (control / "stable-update.started.json").write_text(
        json.dumps(dict(phase="stable-update", previous_request=None, current="0.1.0"))
    )
    (control / "stable-update.result.json").write_text(
        json.dumps(dict(phase="stable-update", root=root, request_id=request))
    )
    module.JOURNAL.write_text(json.dumps(root))
    module.JOURNAL.chmod(0o600)
    archive = paths.CONFIG / ".updater-state" / ("archive-" + request + ".tar.gz")
    archive.write_bytes(b"sealed fixture archive")
    archive.chmod(0o400)
    snapshot = paths.CONFIG / ".updater-state" / ("snapshot-" + request + ".json")
    entry = original[str(paths.CONFIG / "config.json")]
    snapshot.write_text(
        json.dumps(
            dict(
                format_version=1,
                request_id=request,
                files={
                    "config.json": dict(
                        present=True,
                        bytes=base64.b64encode(original_config).decode(),
                        **{k: entry[k] for k in ("uid", "gid", "mode")},
                    )
                },
            )
        )
    )
    snapshot.chmod(0o600)
    manifest = dict(
        files={
            "artifacts/normal-0.1.1/knx_to_openhab-0.1.1.tar.gz": dict(
                size=archive.stat().st_size, sha256=module.digest(archive.read_bytes())
            )
        }
    )
    (paths.BASE / "releases/0.1.1").mkdir()
    (paths.BASE / "current").unlink()
    (paths.BASE / "current").symlink_to(paths.BASE / "releases/0.1.1", target_is_directory=True)
    (paths.PREPARATION / request).mkdir()
    update = paths.DATA / "update"
    update.mkdir(mode=0o700)
    os.chown(update, 999, 989)
    (update / "request.json").write_text(
        json.dumps(dict(format_version=1, request_id=request, channel="stable"))
    )
    (update / "request.json").chmod(0o600)
    os.chown(update / "request.json", 999, 989)
    (update / "submit.lock").write_bytes(b"")
    (update / "submit.lock").chmod(0o600)
    os.chown(update / "submit.lock", 999, 989)
    (paths.DATA / "sessions.sqlite3").write_bytes(b"test store metadata only")
    status = dict(
        format_version=1, phase="committed", request_id=request, message="Release update completed"
    )
    (paths.CONFIG / ".updater-status.json").write_text(
        json.dumps(status, sort_keys=True, separators=(",", ":"))
    )
    (paths.CONFIG / ".updater-log.txt").write_bytes(b"committed: Release update completed\n")

    def observe():
        entries = {str(p): repair.inventory_entry(p, details=True) for p in listed}
        entries["/etc/hosts"] = repair.inventory_entry(hosts, details=True)
        entries[str(unit)] = repair.inventory_entry(unit, details=True)
        return dict(entries=entries)

    return module, baseline, manifest, observe


def test_genuine_validated_own_transaction_inventory_is_admitted(admitted_transaction_tree):
    module, baseline, manifest, observe = admitted_transaction_tree
    assert len(module.admit_inventory(baseline, observe(), None, None, manifest)) == 1


@pytest.mark.parametrize(
    "foreign",
    [
        "archive-99999999-9999-4999-8999-999999999999.tar.gz",
        "snapshot-99999999-9999-4999-8999-999999999999.json",
        "terminal-99999999-9999-4999-8999-999999999999.json",
    ],
)
def test_post_request_state_rejects_unrelated_protected_artifacts(
    admitted_transaction_tree, foreign
):
    module, baseline, manifest, observe = admitted_transaction_tree
    path = module.state.CONFIG / ".updater-state" / foreign
    path.write_bytes(b"unknown")
    before = path.read_bytes()
    with pytest.raises(ValueError):
        module.admit_inventory(baseline, observe(), None, None, manifest)
    assert path.read_bytes() == before
