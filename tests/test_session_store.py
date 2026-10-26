import base64

import pytest

from web_ui.backend.session_store import (
    LOGIN_FAILURE_LIMIT,
    LOGIN_LOCKOUT,
    SessionStore,
)


def test_session_lifecycle_and_csrf_binding(tmp_path):
    path = tmp_path / "data/sessions.sqlite3"
    store = SessionStore(path, b"s" * 32)

    token, csrf_token = store.create("operator", max_age=60)

    session = store.get(token)
    assert session is not None
    assert session.username == "operator"
    assert store.verify_csrf(token, csrf_token)
    assert not store.verify_csrf(token, "wrong-token")
    assert path.stat().st_mode & 0o777 == 0o600

    store.revoke(token)
    assert store.get(token) is None
    assert not store.verify_csrf(token, csrf_token)


def test_expired_session_is_removed(tmp_path):
    store = SessionStore(tmp_path / "sessions.sqlite3", b"s" * 32)
    token, _ = store.create("operator", max_age=5)
    session = store.get(token)

    assert session is not None
    assert store.get(token, now=session.expires_at) is None


def test_credential_change_revokes_existing_session(tmp_path):
    store = SessionStore(tmp_path / "sessions.sqlite3", b"s" * 32)
    token, _ = store.create("operator", credential_version="credential-v1")

    assert store.get(token, credential_version="credential-v1") is not None
    assert store.get(token, credential_version="credential-v2") is None
    assert store.get(token, credential_version="credential-v1") is None


def test_existing_session_database_adds_credential_version_column(tmp_path):
    import sqlite3

    path = tmp_path / "sessions.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute("""CREATE TABLE sessions (
                   token_hash TEXT PRIMARY KEY,
                   username TEXT NOT NULL,
                   csrf_hash TEXT NOT NULL,
                   created_at REAL NOT NULL,
                   expires_at REAL NOT NULL
               )""")

    store = SessionStore(path, b"s" * 32)
    token, _ = store.create("operator", credential_version="credential-v1")

    assert store.get(token, credential_version="credential-v1") is not None


def test_login_attempts_lock_and_expire(tmp_path):
    store = SessionStore(tmp_path / "sessions.sqlite3", b"s" * 32)

    assert store.is_login_allowed("127.0.0.1", now=100)
    for _ in range(LOGIN_FAILURE_LIMIT):
        store.record_login_failure("127.0.0.1", now=100)
    assert not store.is_login_allowed("127.0.0.1", now=101)
    assert store.is_login_allowed("127.0.0.1", now=100 + LOGIN_LOCKOUT)


def test_session_secret_is_durable_and_private(tmp_path, monkeypatch):
    config_dir = tmp_path / "etc"
    config_dir.mkdir()
    data_dir = tmp_path / "data"
    monkeypatch.setenv("KNXOH_INSTALL_DIR", str(tmp_path))
    monkeypatch.setenv("KNXOH_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("KNXOH_DATA_DIR", str(data_dir))
    monkeypatch.setenv("KNXOH_BACKUP_DIR", str(tmp_path / "backups"))
    monkeypatch.setenv("KNXOH_PATHS_FILE", str(tmp_path / "missing-paths.env"))
    from web_ui.backend.storage import get_session_secret

    first = get_session_secret(tmp_path)
    second = get_session_secret(tmp_path)

    assert first == second
    assert len(first) >= 32
    assert (data_dir / "session.secret").stat().st_mode & 0o777 == 0o600


def test_session_secret_rejects_symlink(tmp_path, monkeypatch):
    config_dir = tmp_path / "etc"
    config_dir.mkdir()
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    external_secret = tmp_path / "external.secret"
    external_secret.write_bytes(b"x" * 32)
    (data_dir / "session.secret").symlink_to(external_secret)
    monkeypatch.setenv("KNXOH_INSTALL_DIR", str(tmp_path))
    monkeypatch.setenv("KNXOH_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("KNXOH_DATA_DIR", str(data_dir))
    monkeypatch.setenv("KNXOH_BACKUP_DIR", str(tmp_path / "backups"))
    monkeypatch.setenv("KNXOH_PATHS_FILE", str(tmp_path / "missing-paths.env"))
    from web_ui.backend.storage import get_session_secret

    with pytest.raises(ValueError, match="must not be a symlink"):
        get_session_secret(tmp_path)


def test_configured_session_secret_is_decoded_and_validated(tmp_path, monkeypatch):
    from web_ui.backend.storage import get_session_secret

    config_dir = tmp_path / "etc"
    config_dir.mkdir()
    data_dir = tmp_path / "data"
    monkeypatch.setenv("KNXOH_INSTALL_DIR", str(tmp_path))
    monkeypatch.setenv("KNXOH_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("KNXOH_DATA_DIR", str(data_dir))
    monkeypatch.setenv("KNXOH_BACKUP_DIR", str(tmp_path / "backups"))
    monkeypatch.setenv("KNXOH_PATHS_FILE", str(tmp_path / "missing-paths.env"))
    configured = b"c" * 32
    encoded = base64.b64encode(configured).decode("ascii")
    (config_dir / "secrets.env").write_text(f"KNXOH_SESSION_SECRET_B64={encoded}\n")

    assert get_session_secret(tmp_path) == configured
    assert not (data_dir / "session.secret").exists()
