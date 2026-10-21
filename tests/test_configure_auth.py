import base64
import json

import pytest

from installer.configure_auth import configure_auth
from web_ui.backend.auth import verify_password


def _config(path, password=None):
    auth = {"enabled": True, "user": "admin"}
    if password is not None:
        auth["password"] = password
    path.write_text(json.dumps({"auth": auth}), encoding="utf-8")


def test_first_run_stores_hash_without_plaintext(tmp_path):
    config_path = tmp_path / "config.json"
    secrets_path = tmp_path / "secrets.env"
    _config(config_path)

    changed = configure_auth(
        config_path,
        secrets_path,
        password_provider=lambda: "user-chosen-long-passphrase",
    )

    assert changed
    assert "user-chosen-long-passphrase" not in secrets_path.read_text(encoding="utf-8")
    secret_line = secrets_path.read_text(encoding="utf-8").strip()
    assert secret_line.startswith("KNXOH_UI_PASSWORD_HASH_B64=")
    password_hash = base64.b64decode(secret_line.split("=", 1)[1]).decode("utf-8")
    assert verify_password(password_hash, "user-chosen-long-passphrase")
    assert "password" not in json.loads(config_path.read_text(encoding="utf-8"))["auth"]
    assert secrets_path.stat().st_mode & 0o777 == 0o640


def test_configure_auth_migrates_existing_password_without_prompting(tmp_path):
    config_path = tmp_path / "config.json"
    secrets_path = tmp_path / "secrets.env"
    _config(config_path, password="existing-short-password")

    def prompt_forbidden():
        raise AssertionError("existing passwords must be migrated without prompting")

    configure_auth(config_path, secrets_path, password_provider=prompt_forbidden)

    hash_line = next(
        line
        for line in secrets_path.read_text(encoding="utf-8").splitlines()
        if line.startswith("KNXOH_UI_PASSWORD_HASH_B64=")
    )
    password_hash = base64.b64decode(hash_line.split("=", 1)[1]).decode("utf-8")
    assert verify_password(password_hash, "existing-short-password")
    assert "existing-short-password" not in config_path.read_text(encoding="utf-8")


def test_configure_auth_refuses_short_first_run_password(tmp_path):
    config_path = tmp_path / "config.json"
    secrets_path = tmp_path / "secrets.env"
    _config(config_path)

    with pytest.raises(ValueError, match="at least 12 characters"):
        configure_auth(config_path, secrets_path, password_provider=lambda: "short")
    assert not secrets_path.exists()


def test_configure_auth_replaces_shipped_default_with_a_new_password(tmp_path):
    config_path = tmp_path / "config.json"
    secrets_path = tmp_path / "secrets.env"
    config_path.write_text(
        json.dumps({"auth": {"enabled": True, "user": "admin", "password": "logihome"}}),
        encoding="utf-8",
    )
    secrets_path.write_text("KEEP=value\n", encoding="utf-8")

    configure_auth(
        config_path,
        secrets_path,
        password_provider=lambda: "new-unique-passphrase",
    )

    hash_line = next(
        line
        for line in secrets_path.read_text(encoding="utf-8").splitlines()
        if line.startswith("KNXOH_UI_PASSWORD_HASH_B64=")
    )
    password_hash = base64.b64decode(hash_line.split("=", 1)[1]).decode("utf-8")
    assert verify_password(password_hash, "new-unique-passphrase")
    assert "logihome" not in secrets_path.read_text(encoding="utf-8")
    assert "password" not in json.loads(config_path.read_text(encoding="utf-8"))["auth"]


def test_configure_auth_does_not_overwrite_existing_hash(tmp_path):
    config_path = tmp_path / "config.json"
    secrets_path = tmp_path / "secrets.env"
    _config(config_path)
    secrets_path.write_text("OTHER_SETTING=keep\n", encoding="utf-8")

    configure_auth(
        config_path,
        secrets_path,
        password_provider=lambda: "another-user-chosen-password",
    )
    first_hash = secrets_path.read_text(encoding="utf-8")

    configure_auth(config_path, secrets_path, password_provider=lambda: pytest.fail("prompted"))

    assert secrets_path.read_text(encoding="utf-8") == first_hash
    assert "OTHER_SETTING=keep" in first_hash
