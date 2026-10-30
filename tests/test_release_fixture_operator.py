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
