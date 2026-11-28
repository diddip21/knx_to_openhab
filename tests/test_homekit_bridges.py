"""HomeKit bridge provisioning against an actual local HTTP protocol adapter."""

import base64
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from web_ui.backend.homekit_bridges import HomekitBridgeClient, HomekitBridgeError


@pytest.fixture
def openhab(tmp_path):
    state = {
        "config": {
            "instances": 1,
            "port": 9123,
            "pin": "test-pin-secret",
            "name": "Test Home",
            "networkInterface": "127.0.0.1",
            "useOHmDNS": True,
        },
        "requests": [],
        "status": 200,
        "retain": True,
        "bad_json": False,
    }

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_GET(self):
            state["requests"].append(("GET", self.path, self.headers.get("Authorization")))
            self.send_response(state["status"])
            if state["status"] == 302:
                self.send_header("Location", "/must-not-follow")
            self.end_headers()
            result = (
                state["config"] if self.path.endswith("/config") else {"id": "org.openhab.homekit"}
            )
            self.wfile.write(b"bad json" if state["bad_json"] else json.dumps(result).encode())

        def do_PUT(self):
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            state["requests"].append(("PUT", self.path, payload))
            if state["retain"]:
                state["config"].update(payload)
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"pin":"must-not-be-returned"}')

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    token_file = tmp_path / "token"
    token_file.write_text("test-api-secret", encoding="utf-8")
    client = HomekitBridgeClient(
        f"http://127.0.0.1:{server.server_port}", token_file, tmp_path / "openhab"
    )
    yield client, state
    server.shutdown()
    server.server_close()
    thread.join(timeout=3)


def test_create_bridges_changes_only_instances_and_verifies(openhab):
    client, state = openhab
    before = dict(state["config"])
    result = client.ensure_count(2)
    assert state["config"] == {**before, "instances": 2}
    assert [request[2] for request in state["requests"] if request[0] == "PUT"] == [
        {"instances": 2}
    ]
    assert result == {
        "requested_count": 2,
        "previous_count": 1,
        "configured_count": 2,
        "changed": True,
        "first_port": 9123,
        "last_port": 9124,
        "runtime_status": "not_checked",
    }
    serialized = json.dumps(result)
    assert "secret" not in serialized and "pin" not in serialized and "Test Home" not in serialized
    expected_auth = "Basic " + base64.b64encode(b"test-api-secret:").decode()
    assert all(r[2] == expected_auth for r in state["requests"] if r[0] == "GET")
    assert state["requests"][-1][0] == "GET"


@pytest.mark.parametrize("requested", [1, 2, 3])
def test_existing_bridges_are_never_reduced_or_rewritten(openhab, requested):
    client, state = openhab
    state["config"]["instances"] = 3
    result = client.ensure_count(requested)
    assert result["configured_count"] == 3
    assert result["changed"] is False
    assert all(r[0] == "GET" for r in state["requests"])


def test_default_configuration_and_missing_token_are_supported(openhab):
    client, state = openhab
    state["config"] = {}
    client.token_file.unlink()
    assert client.status() == {
        "configured_count": 1,
        "first_port": 9123,
        "last_port": 9123,
        "runtime_status": "not_checked",
    }
    assert all(r[2] is None for r in state["requests"])


@pytest.mark.parametrize("count", [0, -1, True, "2", 1.5, None, [], {}])
def test_invalid_requested_count_never_contacts_openhab(openhab, count):
    client, state = openhab
    with pytest.raises(ValueError, match="homekit_bridge_count"):
        client.ensure_count(count)
    assert state["requests"] == []


@pytest.mark.parametrize(
    "status, code",
    [
        (401, "credentials"),
        (403, "credentials"),
        (404, "addon_missing"),
        (500, "unavailable"),
        (302, "unavailable"),
    ],
)
def test_errors_are_sanitized_and_redirects_not_followed(openhab, status, code):
    client, state = openhab
    state["status"] = status
    with pytest.raises(HomekitBridgeError) as caught:
        client.ensure_count(2)
    assert caught.value.code == code
    assert "secret" not in str(caught.value)
    assert len(state["requests"]) == 1


def test_failed_verification_is_not_reported_as_success(openhab):
    client, state = openhab
    state["retain"] = False
    with pytest.raises(HomekitBridgeError, match="did not retain"):
        client.ensure_count(2)


@pytest.mark.parametrize("bad", [True, "not-a-number", 0, -1, [], None])
def test_invalid_openhab_configuration_never_gets_written(openhab, bad):
    client, state = openhab
    state["config"]["instances"] = bad
    with pytest.raises(HomekitBridgeError, match="Invalid HomeKit"):
        client.ensure_count(2)
    assert not any(r[0] == "PUT" for r in state["requests"])


def test_port_overflow_and_invalid_json_fail_without_write(openhab):
    client, state = openhab
    state["config"]["port"] = 65535
    with pytest.raises(HomekitBridgeError, match="TCP port range"):
        client.ensure_count(2)
    state["bad_json"] = True
    with pytest.raises(HomekitBridgeError, match="Invalid HomeKit configuration response"):
        client.status()
    assert not any(r[0] == "PUT" for r in state["requests"])


@pytest.mark.parametrize(
    "url",
    [
        "https://example.org",
        "http://127.0.0.1:0",
        "http://127.0.0.1:bad",
        "http://user:secret@localhost:8080",
        "http://localhost:8080?token=secret",
        "http://localhost:8080/other",
        "http://[",
    ],
)
def test_connection_cannot_send_tokens_to_arbitrary_hosts_or_redirects(tmp_path, url):
    with pytest.raises(HomekitBridgeError):
        HomekitBridgeClient(url, tmp_path / "token")


@pytest.mark.parametrize(
    "filename, content",
    [
        ("homekit.cfg", "instances=1\npin=test-pin-secret\n"),
        ("custom.cfg", "org.openhab.homekit:instances=1\n"),
        ("custom.cfg", "pid:org.openhab.homekit\nname=Example\n"),
    ],
)
def test_file_managed_instances_are_not_silently_overridden(openhab, filename, content):
    client, state = openhab
    services = client.openhab_root / "services"
    services.mkdir(parents=True)
    target = services / filename
    target.write_text(content, encoding="utf-8")
    with pytest.raises(HomekitBridgeError) as caught:
        client.ensure_count(2)
    assert caught.value.code == "file_managed"
    assert target.read_text(encoding="utf-8") == content
    assert not any(r[0] == "PUT" for r in state["requests"])


def test_unrelated_file_managed_options_do_not_block_instances_update(openhab):
    client, state = openhab
    services = client.openhab_root / "services"
    services.mkdir(parents=True)
    target = services / "homekit.cfg"
    target.write_text("org.openhab.homekit:pin=test-pin-secret\n# instances=1\n", encoding="utf-8")
    assert client.ensure_count(2)["configured_count"] == 2
    assert "test-pin-secret" in target.read_text(encoding="utf-8")


def test_api_validates_input_and_uses_real_http_adapter(openhab, monkeypatch):
    from web_ui.backend import app as app_module
    from web_ui.backend import homekit_bridges

    remote, state = openhab
    monkeypatch.setitem(app_module.cfg["auth"], "enabled", False)
    monkeypatch.setattr(homekit_bridges, "configured_client", lambda *_args: remote)
    client = app_module.app.test_client()
    for payload in ({}, [], {"count": True}, {"count": 0}, {"count": "2"}):
        assert client.post("/api/homekit/bridges", json=payload).status_code == 400
    assert state["requests"] == []
    response = client.post("/api/homekit/bridges", json={"count": 2})
    assert response.status_code == 200
    assert response.json["configured_count"] == 2
    assert "secret" not in response.get_data(as_text=True)
    assert client.get("/api/homekit/bridges").json["configured_count"] == 2
    state["status"] = 401
    response = client.post("/api/homekit/bridges", json={"count": 3})
    assert response.status_code == 503 and response.json["code"] == "credentials"


def test_api_requires_authentication_before_contacting_openhab(openhab, monkeypatch):
    from web_ui.backend import app as app_module
    from web_ui.backend import homekit_bridges

    remote, state = openhab
    monkeypatch.setitem(app_module.cfg["auth"], "enabled", True)
    monkeypatch.setitem(app_module.cfg["auth"], "legacy_password", "test-only-password")
    monkeypatch.setitem(app_module.cfg["auth"], "mode", "basic")
    monkeypatch.setitem(app_module.cfg["auth"], "user", "homekit-test")
    monkeypatch.delitem(app_module.cfg["auth"], "password_hash", raising=False)
    monkeypatch.setattr(homekit_bridges, "configured_client", lambda *_args: remote)
    client = app_module.app.test_client()
    assert client.get("/api/homekit/bridges").status_code in (302, 401)
    assert client.post("/api/homekit/bridges", json={"count": 2}).status_code in (302, 401)
    authorization = "Basic " + base64.b64encode(b"homekit-test:test-only-password").decode()
    assert (
        client.post(
            "/api/homekit/bridges",
            json={"count": 2},
            headers={"Authorization": authorization, "Origin": "https://untrusted.example"},
        ).status_code
        == 403
    )
    assert state["requests"] == []


def test_timeout_has_no_secret_details_or_automatic_retry(openhab, monkeypatch):
    client, state = openhab

    def timeout(*_args, **kwargs):
        assert kwargs["timeout"] == 5
        raise TimeoutError("test-api-secret: sensitive response")

    monkeypatch.setattr(client.opener, "open", timeout)
    with pytest.raises(HomekitBridgeError) as caught:
        client.ensure_count(2)
    assert "secret" not in str(caught.value)
    assert state["requests"] == []


def test_cli_uses_same_additive_client_and_sanitized_output(openhab, monkeypatch, capsys):
    from web_ui.backend import homekit_bridges

    client, state = openhab
    monkeypatch.setattr(homekit_bridges, "configured_client", lambda *_args: client)
    monkeypatch.setattr("sys.argv", ["homekit_bridges", "--count", "2"])
    homekit_bridges.main()
    result = json.loads(capsys.readouterr().out)
    assert result["configured_count"] == 2
    assert "secret" not in json.dumps(result)
    assert state["config"]["instances"] == 2


def test_factory_checks_the_effective_generator_root_not_the_web_fallback(tmp_path, monkeypatch):
    from config import config
    from web_ui.backend.homekit_bridges import configured_client

    actual = tmp_path / "actual-openhab"
    monkeypatch.setitem(config, "openhab_path", str(actual))
    client = configured_client(tmp_path / "wrong-web-fallback")
    assert client.openhab_root == actual
