"""Release facade compatibility: never compare branches or launch scripts."""

import json
from unittest.mock import Mock

import pytest

from installer.update_core.transaction import UpdateResult
from web_ui.backend.updater import Updater


def release(version, prerelease=False):
    name = f"knx_to_openhab-{version}.tar.gz"
    base = f"https://github.com/diddip21/knx_to_openhab/releases/download/v{version}/"
    return {
        "tag_name": f"v{version}",
        "draft": False,
        "prerelease": prerelease,
        "assets": [{"name": n, "browser_download_url": base + n} for n in (name, name + ".sha256")],
    }


def test_trigger_submits_without_chmod_popen_or_release_log(monkeypatch, tmp_path):
    submit = Mock(return_value=UpdateResult("submitted", request_id="request"))
    monkeypatch.setattr("web_ui.backend.updater.submit_update", submit)
    assert Updater(str(tmp_path)).trigger_update()[0]
    assert submit.call_args.args[1] == "stable"
    assert Updater(str(tmp_path)).last_update_request_id is None
    assert list(tmp_path.iterdir()) == []


def test_trigger_error_code_is_request_local(tmp_path):
    import threading

    updater = Updater(str(tmp_path))
    updater.last_update_status = "busy"
    worker = threading.Thread(target=lambda: setattr(updater, "last_update_status", "failed"))
    worker.start()
    worker.join()
    assert updater.last_update_status == "busy"


@pytest.mark.parametrize(
    "phase,message,outcome",
    [
        ("claimed", "Update request claimed", "running"),
        ("checking", "Waiting for readiness", "running"),
        ("committed", "Release update completed", "updated"),
        ("rolled-back", "No newer compatible release", "no-update"),
        ("rolled-back", "Update failed; previous release preserved", "failed"),
        ("recovery-failed", "Update recovery requires administrator intervention", "blocked"),
        ("recovered-awaiting-start", "Recovered", "blocked"),
    ],
)
def test_protected_status_exposes_correlated_outcome(
    monkeypatch, tmp_path, phase, message, outcome
):
    request_id = "10000000-0000-4000-8000-000000000001"
    monkeypatch.setattr(
        "web_ui.backend.updater.read_status",
        lambda paths: {
            "format_version": 1,
            "request_id": request_id,
            "phase": phase,
            "message": message,
        },
    )
    value = Updater(str(tmp_path)).get_update_status()
    assert value == {
        "request_id": request_id,
        "phase": phase,
        "message": message,
        "outcome": outcome,
    }


@pytest.mark.parametrize("channel", [None, "beta", "", [], {}])
def test_trigger_validates_before_effects(channel, tmp_path):
    assert not Updater(str(tmp_path)).trigger_update(channel)[0]
    assert list(tmp_path.iterdir()) == []


def test_release_check_keeps_honest_compatibility_fields(monkeypatch, tmp_path):
    (tmp_path / "VERSION").write_text("1.0.0\n")
    download = Mock(return_value=json.dumps(release("1.1.0")).encode())
    monkeypatch.setattr("web_ui.backend.updater.download", download)
    updater = Updater(str(tmp_path))
    monkeypatch.setattr(updater, "_run_git_command", Mock(side_effect=AssertionError("Git")))
    info = updater.check_for_updates()
    assert info["update_available"] is True
    assert info["current_version"] == "1.0.0"
    assert info["latest_version"] == "1.1.0"
    assert info["current_commit"] == info["latest_commit_full"] == "unknown"
    assert download.call_args.args[0].endswith("/releases/latest")


def test_prerelease_highest_genuine_prerelease(monkeypatch, tmp_path):
    (tmp_path / "VERSION").write_text("1.0.0")
    values = [release("9.0.0"), release("2.0.0-rc.2", True), release("2.0.0-rc.10", True)]
    monkeypatch.setattr("web_ui.backend.updater.download", lambda *a: json.dumps(values).encode())
    assert Updater(str(tmp_path)).check_for_updates("prerelease")["latest_version"] == "2.0.0-rc.10"


@pytest.mark.parametrize("version", ["1.1.0", "1.1.0+build", "2.0.0"])
def test_release_no_update_semver(monkeypatch, tmp_path, version):
    (tmp_path / "VERSION").write_text(version)
    monkeypatch.setattr(
        "web_ui.backend.updater.download", lambda *a: json.dumps(release("1.1.0")).encode()
    )
    assert Updater(str(tmp_path)).check_for_updates()["update_available"] is False


def test_metadata_failure_and_unknown_local_version_are_not_updates(monkeypatch, tmp_path):
    monkeypatch.setattr("web_ui.backend.updater.download", lambda *a: b"{}")
    assert "error" in Updater(str(tmp_path)).check_for_updates()
    (tmp_path / "VERSION").write_text("1.0.0")
    assert "error" in Updater(str(tmp_path)).check_for_updates()


@pytest.mark.parametrize("damage", [None, "symlink", "hardlink", "large", "control", "writable"])
def test_log_only_bounded_root_owned_projection(monkeypatch, damage):
    import os
    import tempfile
    from pathlib import Path

    from installer.update_core.protocol import Paths

    if os.name != "posix" or os.geteuid() != 0:
        pytest.skip("Linux root-private protected-log fixture")
    with tempfile.TemporaryDirectory(prefix="task8-log-", dir="/root") as root:
        root = Path(root)
        log = root / ".updater-log.txt"
        log.write_text("claimed: Update request claimed\n")
        if damage == "symlink":
            log.rename(root / "target")
            log.symlink_to(root / "target")
        elif damage == "hardlink":
            os.link(log, root / "alias")
        elif damage == "large":
            log.write_text("x" * 4097)
        elif damage == "control":
            log.write_text("\x1b[31m")
        elif damage == "writable":
            log.chmod(0o666)
        updater = Updater(str(root))
        monkeypatch.setattr(
            updater, "_paths", lambda: Paths(root / "releases", root / "current", root)
        )
        output = updater.get_update_log()
        assert output == (
            "claimed: Update request claimed\n"
            if damage is None
            else "Error reading log: protected update log is unavailable or unsafe."
        )
