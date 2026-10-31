import base64
import builtins
import io
import json
import sys

import pytest

import installer.configure_auth as configure_auth_module
from installer.configure_auth import _prompt_password, configure_auth
from web_ui.backend.auth import verify_password


def test_prompt_password_opens_terminal_write_only(monkeypatch):
    terminal = io.StringIO()
    answers = iter(["a-strong-user-password", "a-strong-user-password"])
    opened_modes = []

    def fake_open(path, mode, encoding):
        assert path == "/dev/tty"
        opened_modes.append(mode)
        return terminal

    monkeypatch.setattr(builtins, "open", fake_open)
    monkeypatch.setattr(
        "installer.configure_auth.getpass.getpass",
        lambda _prompt, stream: next(answers),
    )

    assert _prompt_password() == "a-strong-user-password"
    assert opened_modes == ["w"]


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
    secret_values = dict(
        line.split("=", 1) for line in secrets_path.read_text(encoding="utf-8").splitlines()
    )
    password_hash = base64.b64decode(secret_values["KNXOH_UI_PASSWORD_HASH_B64"]).decode("utf-8")
    assert verify_password(password_hash, "user-chosen-long-passphrase")
    assert len(base64.b64decode(secret_values["KNXOH_SESSION_SECRET_B64"])) >= 32
    assert "password" not in json.loads(config_path.read_text(encoding="utf-8"))["auth"]
    assert secrets_path.stat().st_mode & 0o777 == 0o640


def test_cli_generates_and_reports_password_without_terminal_input(monkeypatch, tmp_path, capsys):
    config_path = tmp_path / "config.json"
    secrets_path = tmp_path / "secrets.env"
    _config(config_path)
    monkeypatch.setattr(
        sys,
        "argv",
        ["configure_auth.py", "--config", str(config_path), "--secrets", str(secrets_path)],
    )

    configure_auth_module.main()

    output = capsys.readouterr().out
    password = output.splitlines()[-1]
    values = dict(line.split("=", 1) for line in secrets_path.read_text().splitlines())
    password_hash = base64.b64decode(values["KNXOH_UI_PASSWORD_HASH_B64"]).decode("utf-8")
    assert "shown once" in output
    assert len(password) >= 12
    assert verify_password(password_hash, password)
    assert password not in secrets_path.read_text(encoding="utf-8")


def test_configure_auth_migrates_existing_password_without_prompting(tmp_path):
    config_path = tmp_path / "config.json"
    secrets_path = tmp_path / "secrets.env"
    _config(config_path, password="existing-short-password")

    def prompt_forbidden():
        raise AssertionError("existing passwords must be migrated without prompting")

    configure_auth(config_path, secrets_path, password_provider=prompt_forbidden)

    secret_values = dict(
        line.split("=", 1) for line in secrets_path.read_text(encoding="utf-8").splitlines()
    )
    password_hash = base64.b64decode(secret_values["KNXOH_UI_PASSWORD_HASH_B64"]).decode("utf-8")
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
    _config(config_path, password="logihome")

    configure_auth(
        config_path,
        secrets_path,
        password_provider=lambda: "new-unique-passphrase",
    )

    values = dict(line.split("=", 1) for line in secrets_path.read_text().splitlines())
    password_hash = base64.b64decode(values["KNXOH_UI_PASSWORD_HASH_B64"]).decode("utf-8")
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


def test_configure_auth_preserves_existing_session_secret(tmp_path):
    config_path = tmp_path / "config.json"
    secrets_path = tmp_path / "secrets.env"
    _config(config_path)
    session_secret = base64.b64encode(b"x" * 32).decode("ascii")
    secrets_path.write_text(f"KEEP_ME=yes\nKNXOH_SESSION_SECRET_B64={session_secret}\n")

    configure_auth(config_path, secrets_path, password_provider=lambda: "new-strong-password-here")

    values = dict(line.split("=", 1) for line in secrets_path.read_text().splitlines())
    assert values["KEEP_ME"] == "yes"
    assert values["KNXOH_SESSION_SECRET_B64"] == session_secret
    assert (
        len(
            [
                line
                for line in secrets_path.read_text().splitlines()
                if line.startswith("KNXOH_SESSION_SECRET_B64=")
            ]
        )
        == 1
    )
