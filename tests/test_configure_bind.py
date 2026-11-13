import json
import stat

from installer.configure_bind import _confirm_external_access, configure_bind


def _config(path, bind_host):
    path.write_text(json.dumps({"bind_host": bind_host, "port": 8085}), encoding="utf-8")


def test_loopback_bind_needs_no_migration_prompt(tmp_path):
    config_path = tmp_path / "config.json"
    _config(config_path, "127.0.0.1")

    assert not configure_bind(
        config_path,
        confirm_external=lambda host: (_ for _ in ()).throw(
            AssertionError(f"unexpected prompt for {host}")
        ),
    )
    assert json.loads(config_path.read_text(encoding="utf-8"))["bind_host"] == "127.0.0.1"


def test_legacy_external_bind_requires_explicit_confirmation(tmp_path):
    config_path = tmp_path / "config.json"
    _config(config_path, "0.0.0.0")
    prompts = []

    changed = configure_bind(
        config_path, confirm_external=lambda host: prompts.append(host) or False
    )

    assert changed
    assert prompts == ["0.0.0.0"]
    assert json.loads(config_path.read_text(encoding="utf-8"))["bind_host"] == "127.0.0.1"


def test_staged_fallback_keeps_live_config_unchanged_and_preserves_metadata(tmp_path):
    config_path = tmp_path / "config.json"
    staged_path = tmp_path / "config.json.staged"
    _config(config_path, "192.168.1.10")
    config_path.chmod(0o640)
    original_stat = config_path.stat()

    changed = configure_bind(
        config_path,
        confirm_external=lambda _host: False,
        output_path=staged_path,
    )

    assert changed
    assert json.loads(config_path.read_text(encoding="utf-8"))["bind_host"] == "192.168.1.10"
    assert json.loads(staged_path.read_text(encoding="utf-8"))["bind_host"] == "127.0.0.1"
    staged_stat = staged_path.stat()
    assert stat.S_IMODE(staged_stat.st_mode) == 0o640
    assert (staged_stat.st_uid, staged_stat.st_gid) == (original_stat.st_uid, original_stat.st_gid)


def test_explicit_lan_choice_preserves_existing_bind(tmp_path):
    config_path = tmp_path / "config.json"
    _config(config_path, "192.168.1.10")

    assert not configure_bind(config_path, confirm_external=lambda host: True)
    assert json.loads(config_path.read_text(encoding="utf-8"))["bind_host"] == "192.168.1.10"


def test_unknown_hostname_is_treated_as_external(tmp_path):
    config_path = tmp_path / "config.json"
    _config(config_path, "knx-ui.local")
    prompted = []

    configure_bind(config_path, confirm_external=lambda host: prompted.append(host) or False)

    assert prompted == ["knx-ui.local"]
    assert json.loads(config_path.read_text(encoding="utf-8"))["bind_host"] == "127.0.0.1"


def test_external_bind_confirmation_reads_from_terminal_not_stdin(tmp_path, monkeypatch):
    terminal = tmp_path / "tty"
    terminal.write_text("y\n", encoding="utf-8")

    def reject_stdin(*_args, **_kwargs):
        raise AssertionError("the installer must read confirmation from /dev/tty")

    monkeypatch.setattr("builtins.input", reject_stdin)

    assert _confirm_external_access("0.0.0.0", terminal_path=terminal)


def test_external_bind_confirmation_defaults_to_no_when_terminal_is_unavailable(tmp_path):
    missing_terminal = tmp_path / "missing-tty"

    assert not _confirm_external_access("0.0.0.0", terminal_path=missing_terminal)
