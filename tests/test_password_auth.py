import base64
import json
from unittest.mock import Mock

from web_ui.backend import app as app_module
from web_ui.backend.auth import hash_password, is_password_hash, verify_password
from web_ui.backend.storage import load_config


def test_password_hash_is_argon2id_and_verifies_only_matching_password():
    password_hash = hash_password("a-long-unique-password")

    assert is_password_hash(password_hash)
    assert verify_password(password_hash, "a-long-unique-password")
    assert not verify_password(password_hash, "a-different-password")
    assert not verify_password("not-a-hash", "a-long-unique-password")
    assert not is_password_hash(password_hash + "$trailing")
    assert not is_password_hash(password_hash[:-1])


def test_rate_limiter_expires_failures_and_bounds_clients():
    now = [0.0]
    limiter = app_module.AuthRateLimiter(
        max_attempts=2, window_seconds=10, max_clients=2, clock=lambda: now[0]
    )

    limiter.record_failure("one")
    limiter.record_failure("one")
    assert limiter.is_limited("one")
    limiter.record_failure("two")
    limiter.record_failure("three")
    assert len(limiter._failures) == 2
    now[0] = 11.0
    assert not limiter.is_limited("one")


def test_basic_auth_uses_hash_and_sets_session_cookie(monkeypatch):
    password_hash = hash_password("a-long-unique-password")
    monkeypatch.setattr(
        app_module,
        "cfg",
        {"auth": {"enabled": True, "user": "operator", "password_hash": password_hash}},
    )
    token = base64.b64encode(b"operator:a-long-unique-password").decode("ascii")
    app_module._auth_rate_limiter.reset("127.0.0.1")
    verifier = Mock(wraps=verify_password)
    monkeypatch.setattr(app_module, "verify_password", verifier)

    response = app_module.app.test_client().get("/", headers={"Authorization": f"Basic {token}"})

    assert response.status_code == 200
    assert "knx_session=" in response.headers["Set-Cookie"]
    assert "HttpOnly" in response.headers["Set-Cookie"]
    assert "SameSite=Lax" in response.headers["Set-Cookie"]
    verifier.assert_called_once_with(password_hash, "a-long-unique-password")


def test_basic_auth_rejects_wrong_password(monkeypatch):
    monkeypatch.setattr(
        app_module,
        "cfg",
        {"auth": {"enabled": True, "user": "operator", "password_hash": hash_password("correct")}},
    )
    token = base64.b64encode(b"operator:incorrect").decode("ascii")

    response = app_module.app.test_client().get("/", headers={"Authorization": f"Basic {token}"})

    assert response.status_code == 401


def test_basic_auth_rate_limits_before_expensive_verification(monkeypatch):
    monkeypatch.setattr(
        app_module,
        "cfg",
        {"auth": {"enabled": True, "user": "operator", "password_hash": "valid-looking-hash"}},
    )
    verifier = Mock(return_value=False)
    monkeypatch.setattr(app_module, "verify_password", verifier)
    app_module._auth_rate_limiter.reset("127.0.0.1")
    token = base64.b64encode(b"operator:incorrect").decode("ascii")
    client = app_module.app.test_client()

    responses = [client.get("/", headers={"Authorization": f"Basic {token}"}) for _ in range(6)]

    assert [response.status_code for response in responses] == [401, 401, 401, 401, 401, 429]
    assert verifier.call_count == 5
    app_module._auth_rate_limiter.reset("127.0.0.1")


def test_first_run_without_credentials_fails_closed(monkeypatch):
    monkeypatch.setattr(
        app_module,
        "cfg",
        {"auth": {"enabled": True, "user": "admin"}},
    )

    response = app_module.app.test_client().get("/")

    assert response.status_code == 503
    assert b"credentials are not configured" in response.data.lower()


def test_status_endpoint_remains_public_during_first_run(monkeypatch):
    monkeypatch.setattr(
        app_module,
        "cfg",
        {"auth": {"enabled": True, "user": "admin"}},
    )

    response = app_module.app.test_client().get("/api/status")

    assert response.status_code == 200


def test_update_requires_external_argon2_hash_before_running(monkeypatch):
    monkeypatch.setattr(
        app_module,
        "cfg",
        {"auth": {"enabled": True, "user": "admin", "legacy_password": "old-password"}},
    )
    token = base64.b64encode(b"admin:old-password").decode("ascii")

    response = app_module.app.test_client().post(
        "/api/version/update", headers={"Authorization": f"Basic {token}"}
    )

    assert response.status_code == 409
    assert b"password hash is required" in response.data.lower()


def test_legacy_secret_remains_usable_without_returning_plaintext(tmp_path, monkeypatch):
    config_dir = tmp_path / "etc/knx_to_openhab"
    config_dir.mkdir(parents=True)
    (config_dir / "config.json").write_text(
        json.dumps({"auth": {"enabled": True, "user": "admin"}}), encoding="utf-8"
    )
    password = "preserved-existing-password"
    encoded = base64.b64encode(password.encode("utf-8")).decode("ascii")
    (config_dir / "secrets.env").write_text(f"KNXOH_UI_PASSWORD_B64={encoded}\n", encoding="utf-8")
    monkeypatch.setenv("KNXOH_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("KNXOH_PATHS_FILE", str(tmp_path / "missing-paths.env"))

    loaded = load_config(tmp_path)

    assert loaded["auth"]["legacy_password"] == password
    assert "password" not in loaded["auth"]
