import base64
import json
from unittest.mock import Mock

import itsdangerous.timed
import pytest
from itsdangerous import URLSafeTimedSerializer

from web_ui.backend import app as app_module
from web_ui.backend.auth import hash_password, is_password_hash, verify_password
from web_ui.backend.storage import load_config


def _enable_test_auth(monkeypatch, tmp_path, password="a-long-unique-password"):
    monkeypatch.setattr(
        app_module,
        "cfg",
        {
            "auth": {
                "enabled": True,
                "user": "operator",
                "password_hash": hash_password(password),
            },
            "sessions_file": str(tmp_path / "sessions.sqlite3"),
        },
    )
    monkeypatch.setattr(app_module, "_session_store", None)
    monkeypatch.setattr(app_module, "get_session_secret", lambda project_root=None: b"k" * 32)


def _csrf_cookie(client, path="/login"):
    response = client.get(path)
    assert response.status_code == 200
    cookie = client.get_cookie("knx_login_csrf")
    assert cookie is not None
    return cookie.value


def test_password_hash_is_argon2id_and_verifies_only_matching_password():
    password_hash = hash_password("a-long-unique-password")

    assert is_password_hash(password_hash)
    assert verify_password(password_hash, "a-long-unique-password")
    assert not verify_password(password_hash, "a-different-password")
    assert not verify_password("not-a-hash", "a-long-unique-password")
    assert not is_password_hash(password_hash + "$trailing")
    assert not is_password_hash(password_hash[:-1])

    # This canonical 32-byte digest stays syntactically valid when its final
    # base64 character is removed unless the configured digest length is fixed.
    parts = password_hash.split("$")
    parts[-1] = base64.b64encode(bytes(32)).decode("ascii").rstrip("=")
    canonical_digest_hash = "$".join(parts)
    assert is_password_hash(canonical_digest_hash)
    assert not is_password_hash(canonical_digest_hash[:-1])


def test_login_creates_protected_session_and_logout_revokes_it(monkeypatch, tmp_path):
    _enable_test_auth(monkeypatch, tmp_path)
    client = app_module.app.test_client()
    csrf_token = _csrf_cookie(client, "/login?next=%2F%2Fevil.example")

    response = client.post(
        "/login?next=%2F%2Fevil.example",
        data={
            "csrf_token": csrf_token,
            "username": "operator",
            "password": "a-long-unique-password",
        },
    )

    assert response.status_code == 302
    assert response.headers["Location"] == "/"
    assert "no-store" in response.headers.get("Cache-Control", "")
    cookies = response.headers.getlist("Set-Cookie")
    session_cookie = next(cookie for cookie in cookies if cookie.startswith("knx_session="))
    assert "HttpOnly" in session_cookie
    assert "SameSite=Lax" in session_cookie
    assert any(cookie.startswith("knx_csrf=") for cookie in cookies)

    csrf_header = client.get_cookie("knx_csrf").value
    blocked = client.post("/api/logout")
    assert blocked.status_code == 403

    already_signed_in = client.get("/login")
    assert already_signed_in.status_code == 302
    assert "no-store" in already_signed_in.headers.get("Cache-Control", "")

    logout = client.post("/api/logout", headers={"X-CSRF-Token": csrf_header})
    assert logout.status_code == 200
    assert app_module.app.test_client().get("/").status_code == 302


def test_login_origin_fallback_still_checks_password(monkeypatch, tmp_path):
    _enable_test_auth(monkeypatch, tmp_path)
    app_module.cfg["login_csrf_allowed_origins"] = ["https://mcrelay.greiner-wue.de"]
    client = app_module.app.test_client()
    csrf_token = _csrf_cookie(client)
    client.delete_cookie("knx_login_csrf")

    response = client.post(
        "/login",
        data={"csrf_token": csrf_token, "username": "operator", "password": "wrong"},
        headers={"Origin": "https://mcrelay.greiner-wue.de"},
    )

    assert response.status_code == 401
    assert b"username or password is incorrect" in response.data.lower()
    assert not any(
        cookie.startswith("knx_session=") for cookie in response.headers.getlist("Set-Cookie")
    )


def test_session_and_login_csrf_cookies_are_secure_over_https(monkeypatch, tmp_path):
    _enable_test_auth(monkeypatch, tmp_path)
    client = app_module.app.test_client()
    csrf_token = _csrf_cookie(client, "https://localhost/login")
    csrf_cookie = client.get_cookie("knx_login_csrf")
    assert csrf_cookie is not None and csrf_cookie.secure

    response = client.post(
        "https://localhost/login",
        data={
            "csrf_token": csrf_token,
            "username": "operator",
            "password": "a-long-unique-password",
        },
    )

    assert response.status_code == 302
    session_cookie = next(
        cookie
        for cookie in response.headers.getlist("Set-Cookie")
        if cookie.startswith("knx_session=")
    )
    assert "Secure" in session_cookie
    assert "HttpOnly" in session_cookie
    csrf_session_cookie = next(
        cookie
        for cookie in response.headers.getlist("Set-Cookie")
        if cookie.startswith("knx_csrf=")
    )
    assert "Secure" in csrf_session_cookie


def test_login_rejects_missing_or_invalid_csrf_token(monkeypatch, tmp_path):
    _enable_test_auth(monkeypatch, tmp_path)
    client = app_module.app.test_client()
    _csrf_cookie(client)

    response = client.post(
        "/login",
        data={"username": "operator", "password": "a-long-unique-password"},
    )

    assert response.status_code == 400
    assert b"sign-in request expired" in response.data.lower()


def test_login_allows_missing_csrf_cookie_for_configured_origin(monkeypatch, tmp_path):
    _enable_test_auth(monkeypatch, tmp_path)
    app_module.cfg["login_csrf_allowed_origins"] = ["https://mcrelay.greiner-wue.de"]
    client = app_module.app.test_client()
    csrf_token = _csrf_cookie(client)
    client.delete_cookie("knx_login_csrf")

    response = client.post(
        "/login",
        data={
            "csrf_token": csrf_token,
            "username": "operator",
            "password": "a-long-unique-password",
        },
        headers={"Origin": "https://mcrelay.greiner-wue.de"},
    )

    assert response.status_code == 302
    assert response.headers["Location"] == "/"


def test_login_uses_referer_origin_only_when_origin_is_absent(monkeypatch, tmp_path):
    _enable_test_auth(monkeypatch, tmp_path)
    app_module.cfg["login_csrf_allowed_origins"] = ["https://mcrelay.greiner-wue.de"]
    client = app_module.app.test_client()
    csrf_token = _csrf_cookie(client)
    client.delete_cookie("knx_login_csrf")

    response = client.post(
        "/login",
        data={
            "csrf_token": csrf_token,
            "username": "operator",
            "password": "a-long-unique-password",
        },
        headers={"Referer": "https://mcrelay.greiner-wue.de/login?next=%2F"},
    )

    assert response.status_code == 302


@pytest.mark.parametrize(
    "headers",
    [
        {"Origin": "https://evil.example"},
        {"Origin": "https://mcrelay.greiner-wue.de.evil.example"},
        {"Origin": "null"},
        {"Origin": "not-an-origin"},
        {},
        {
            "Origin": "https://evil.example",
            "Referer": "https://mcrelay.greiner-wue.de/login",
        },
    ],
    ids=["unlisted", "lookalike-host", "null", "malformed", "no-origin", "bad-origin-wins"],
)
def test_login_rejects_missing_cookie_for_untrusted_origin(monkeypatch, tmp_path, headers):
    _enable_test_auth(monkeypatch, tmp_path)
    app_module.cfg["login_csrf_allowed_origins"] = ["https://mcrelay.greiner-wue.de"]
    password_verifier = Mock(return_value=True)
    monkeypatch.setattr(app_module, "verify_password", password_verifier)
    client = app_module.app.test_client()
    csrf_token = _csrf_cookie(client)
    client.delete_cookie("knx_login_csrf")

    response = client.post(
        "/login",
        data={
            "csrf_token": csrf_token,
            "username": "operator",
            "password": "a-long-unique-password",
        },
        headers=headers,
    )

    assert response.status_code == 400
    assert b"sign-in request expired" in response.data.lower()
    password_verifier.assert_not_called()


def test_login_rejects_mismatched_cookie_even_for_configured_origin(monkeypatch, tmp_path):
    _enable_test_auth(monkeypatch, tmp_path)
    app_module.cfg["login_csrf_allowed_origins"] = ["https://mcrelay.greiner-wue.de"]
    client = app_module.app.test_client()
    csrf_token = _csrf_cookie(client)
    client.set_cookie("knx_login_csrf", "different-token")

    response = client.post(
        "/login",
        data={"csrf_token": csrf_token, "username": "operator", "password": "wrong"},
        headers={"Origin": "https://mcrelay.greiner-wue.de"},
    )

    assert response.status_code == 400
    assert b"sign-in request expired" in response.data.lower()


@pytest.mark.parametrize("token_kind", ["tampered", "expired"])
def test_login_rejects_invalid_signed_token_without_cookie(monkeypatch, tmp_path, token_kind):
    _enable_test_auth(monkeypatch, tmp_path)
    app_module.cfg["login_csrf_allowed_origins"] = ["https://mcrelay.greiner-wue.de"]
    if token_kind == "tampered":
        csrf_token = "not-a-valid-signed-token"
    else:
        serializer = URLSafeTimedSerializer(b"k" * 32, salt="knx-login-csrf")
        with monkeypatch.context() as context:
            context.setattr(itsdangerous.timed.time, "time", lambda: 1)
            csrf_token = serializer.dumps("expired-token")
    client = app_module.app.test_client()

    response = client.post(
        "/login",
        data={"csrf_token": csrf_token, "username": "operator", "password": "wrong"},
        headers={"Origin": "https://mcrelay.greiner-wue.de"},
    )

    assert response.status_code == 400
    assert b"sign-in request expired" in response.data.lower()


def test_malformed_configured_login_origin_does_not_authorize_fallback(monkeypatch, tmp_path):
    _enable_test_auth(monkeypatch, tmp_path)
    app_module.cfg["login_csrf_allowed_origins"] = [
        "https://mcrelay.greiner-wue.de/unexpected-path"
    ]
    client = app_module.app.test_client()
    csrf_token = _csrf_cookie(client)
    client.delete_cookie("knx_login_csrf")

    response = client.post(
        "/login",
        data={"csrf_token": csrf_token, "username": "operator", "password": "wrong"},
        headers={"Origin": "https://mcrelay.greiner-wue.de"},
    )

    assert response.status_code == 400
    assert b"sign-in request expired" in response.data.lower()


def test_login_csrf_allowed_origins_default_to_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("KNXOH_PATHS_FILE", str(tmp_path / "missing-paths.env"))
    monkeypatch.delenv("KNXOH_CONFIG_DIR", raising=False)
    monkeypatch.delenv("KNXOH_DATA_DIR", raising=False)
    monkeypatch.delenv("KNXOH_BACKUP_DIR", raising=False)

    assert load_config(tmp_path)["login_csrf_allowed_origins"] == []


@pytest.mark.parametrize("configured_origins", ["https://mcrelay.greiner-wue.de", [1]])
def test_load_config_rejects_invalid_login_csrf_origin_shape(
    tmp_path, monkeypatch, configured_origins
):
    monkeypatch.setenv("KNXOH_PATHS_FILE", str(tmp_path / "missing-paths.env"))
    monkeypatch.delenv("KNXOH_CONFIG_DIR", raising=False)
    monkeypatch.delenv("KNXOH_DATA_DIR", raising=False)
    monkeypatch.delenv("KNXOH_BACKUP_DIR", raising=False)
    config_file = tmp_path / "web_ui" / "backend" / "config.json"
    config_file.parent.mkdir(parents=True)
    config_file.write_text(
        json.dumps({"login_csrf_allowed_origins": configured_origins}), encoding="utf-8"
    )

    with pytest.raises(ValueError, match="login_csrf_allowed_origins"):
        load_config(tmp_path)


def test_login_responses_are_not_cacheable(monkeypatch, tmp_path):
    _enable_test_auth(monkeypatch, tmp_path)
    client = app_module.app.test_client()

    login_page = client.get("/login")
    error_response = client.post("/login")

    assert "no-store" in login_page.headers.get("Cache-Control", "")
    assert "no-store" in error_response.headers.get("Cache-Control", "")


def test_login_redirect_when_auth_is_disabled_is_not_cacheable(monkeypatch, tmp_path):
    _enable_test_auth(monkeypatch, tmp_path)
    app_module.cfg["auth"]["enabled"] = False
    client = app_module.app.test_client()

    response = client.get("/login")

    assert response.status_code == 302
    assert response.headers["Location"] == "/"
    assert "no-store" in response.headers.get("Cache-Control", "")


def test_login_rate_limits_repeated_failures(monkeypatch, tmp_path):
    _enable_test_auth(monkeypatch, tmp_path)
    verifier = Mock(return_value=False)
    monkeypatch.setattr(app_module, "verify_password", verifier)
    client = app_module.app.test_client()

    for _ in range(5):
        csrf_token = _csrf_cookie(client)
        response = client.post(
            "/login",
            data={"csrf_token": csrf_token, "username": "operator", "password": "wrong"},
        )
        assert response.status_code == 401

    csrf_token = client.get_cookie("knx_login_csrf").value
    response = client.post(
        "/login",
        data={"csrf_token": csrf_token, "username": "operator", "password": "wrong"},
    )
    assert response.status_code == 429
    assert verifier.call_count == 5


@pytest.mark.parametrize("changed_field", ["user", "password_hash"])
def test_credential_changes_revoke_existing_sessions(monkeypatch, tmp_path, changed_field):
    _enable_test_auth(monkeypatch, tmp_path)
    client = app_module.app.test_client()
    csrf_token = _csrf_cookie(client)
    login = client.post(
        "/login",
        data={
            "csrf_token": csrf_token,
            "username": "operator",
            "password": "a-long-unique-password",
        },
    )
    assert login.status_code == 302

    if changed_field == "user":
        app_module.cfg["auth"]["user"] = "renamed-operator"
    else:
        app_module.cfg["auth"]["password_hash"] = hash_password("another-long-password")

    protected = client.get("/api/jobs")

    assert protected.status_code == 401


def test_legacy_password_with_non_ascii_characters_authenticates(monkeypatch, tmp_path):
    _enable_test_auth(monkeypatch, tmp_path)
    password = "Büro-Öl-Temperatur-über-12"
    app_module.cfg["auth"].pop("password_hash")
    app_module.cfg["auth"]["legacy_password"] = password
    client = app_module.app.test_client()
    csrf_token = _csrf_cookie(client)

    response = client.post(
        "/login",
        data={"csrf_token": csrf_token, "username": "operator", "password": password},
    )

    assert response.status_code == 302


def test_first_run_without_credentials_fails_closed(monkeypatch, tmp_path):
    monkeypatch.setattr(
        app_module,
        "cfg",
        {"auth": {"enabled": True, "user": "admin"}, "sessions_file": str(tmp_path / "s.db")},
    )
    monkeypatch.setattr(app_module, "get_session_secret", lambda project_root=None: b"k" * 32)

    client = app_module.app.test_client()
    response = client.get("/")

    assert response.status_code == 503
    assert b"credentials are not configured" in response.data.lower()
    assert b'<html lang="de">' in response.data
    assert b'id="languageSelect"' in response.data
    assert b'class="login-error"' in response.data
    assert b'data-i18n="login.error.unconfigured"' in response.data

    login_response = client.get("/login")
    assert login_response.status_code == 503
    assert b'id="languageSelect"' in login_response.data
    assert b'class="login-error"' in login_response.data
    assert b'data-i18n="login.error.unconfigured"' in login_response.data

    api_response = client.get("/api/jobs")
    assert api_response.status_code == 503
    assert b"<html" not in api_response.data


def test_status_endpoint_remains_public_during_first_run(monkeypatch, tmp_path):
    monkeypatch.setattr(
        app_module,
        "cfg",
        {"auth": {"enabled": True, "user": "admin"}, "sessions_file": str(tmp_path / "s.db")},
    )

    response = app_module.app.test_client().get("/api/status")

    assert response.status_code == 200


def test_update_requires_migrated_hash_before_starting_update(monkeypatch, tmp_path):
    monkeypatch.setattr(
        app_module,
        "cfg",
        {
            "auth": {"enabled": True, "user": "operator", "legacy_password": "old-password"},
            "sessions_file": str(tmp_path / "sessions.sqlite3"),
        },
    )
    monkeypatch.setattr(app_module, "_session_store", None)
    monkeypatch.setattr(app_module, "get_session_secret", lambda project_root=None: b"k" * 32)
    client = app_module.app.test_client()
    login_csrf = _csrf_cookie(client)
    login = client.post(
        "/login",
        data={
            "csrf_token": login_csrf,
            "username": "operator",
            "password": "old-password",
        },
    )
    assert login.status_code == 302

    response = client.post(
        "/api/version/update",
        headers={"X-CSRF-Token": client.get_cookie("knx_csrf").value},
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
