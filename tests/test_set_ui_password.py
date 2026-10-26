import base64

import pytest

from installer.set_ui_password import (
    PASSWORD_KEY,
    configured_secrets_file,
    set_ui_password,
)
from web_ui.backend.auth import verify_password


def test_password_update_preserves_other_secrets_and_file_permissions(tmp_path):
    secrets = tmp_path / "secrets.env"
    secrets.write_text(
        "OTHER_SECRET=keep-me\n"
        "KNXOH_UI_PASSWORD_B64=b2xk\n"
        f"{PASSWORD_KEY}=b2xk\n"
        f"{PASSWORD_KEY}=ZHVwbGljYXRl\n",
        encoding="utf-8",
    )
    secrets.chmod(0o640)
    before = secrets.stat()

    set_ui_password(secrets, "new pässword 2026")

    lines = secrets.read_text(encoding="utf-8").splitlines()
    password_lines = [line for line in lines if line.startswith(f"{PASSWORD_KEY}=")]
    assert len(password_lines) == 1
    assert not any(line.startswith("KNXOH_UI_PASSWORD_B64=") for line in lines)
    password_hash = base64.b64decode(password_lines[0].split("=", 1)[1]).decode("utf-8")
    assert verify_password(password_hash, "new pässword 2026")
    assert "new pässword 2026" not in secrets.read_text(encoding="utf-8")
    assert "OTHER_SECRET=keep-me" in lines
    after = secrets.stat()
    assert after.st_uid == before.st_uid
    assert after.st_gid == before.st_gid
    assert after.st_mode & 0o777 == 0o640


def test_password_update_rejects_short_password_and_symlink(tmp_path):
    secrets = tmp_path / "secrets.env"
    secrets.write_text("OTHER_SECRET=value\n", encoding="utf-8")

    with pytest.raises(ValueError, match="at least 12 characters"):
        set_ui_password(secrets, "too-short")
    with pytest.raises(ValueError, match="at least 12 characters"):
        set_ui_password(secrets, "logihome")

    target = tmp_path / "target.env"
    target.write_text("unchanged\n", encoding="utf-8")
    link = tmp_path / "linked-secrets.env"
    link.symlink_to(target)
    with pytest.raises(ValueError, match="regular file"):
        set_ui_password(link, "new password 2026")
    assert target.read_text(encoding="utf-8") == "unchanged\n"


def test_configured_secrets_path_parses_dollar_without_shell_expansion(tmp_path):
    config_dir = tmp_path / "config $with spaces"
    paths_file = tmp_path / "paths.env"
    paths_file.write_text(
        f'KNXOH_CONFIG_DIR="{config_dir}"\n',
        encoding="utf-8",
    )

    assert configured_secrets_file(paths_file) == config_dir / "secrets.env"
