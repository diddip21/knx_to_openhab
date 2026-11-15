"""Tests for the web UI's allowlisted system service controls."""

from unittest.mock import Mock

from web_ui.backend import service_manager


def test_restart_service_rejects_unknown_service_without_running_a_command(monkeypatch):
    run = Mock()
    monkeypatch.setattr(service_manager.subprocess, "run", run)

    ok, message = service_manager.restart_service("openhab.service; id")

    assert not ok
    assert message == "Unsupported service"
    run.assert_not_called()


def test_restart_service_runs_only_an_allowlisted_systemctl_command(monkeypatch):
    run = Mock(return_value=Mock(returncode=0, stdout="", stderr=""))
    monkeypatch.setattr(service_manager.subprocess, "run", run)

    ok, output = service_manager.restart_service("evcc.service")

    assert ok
    assert output == ""
    run.assert_called_once_with(
        ["sudo", "systemctl", "restart", "evcc.service"],
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_status_rejects_unknown_service_without_running_a_command(monkeypatch):
    run = Mock()
    monkeypatch.setattr(service_manager.subprocess, "run", run)

    result = service_manager.get_service_status("anything.service")

    assert result["status"] == "unsupported"
    assert not result["active"]
    run.assert_not_called()


def test_service_status_reads_state_and_timestamps_with_one_systemctl_call(monkeypatch):
    run = Mock(
        return_value=Mock(
            returncode=0,
            stdout=(
                "LoadState=loaded\n"
                "ActiveState=active\n"
                "ActiveEnterTimestamp=Mon 2026-11-02 10:00:00 CET\n"
                "StateChangeTimestamp=Mon 2026-11-02 10:00:00 CET\n"
                "InactiveEnterTimestamp=\n"
            ),
            stderr="",
        )
    )
    monkeypatch.setattr(service_manager.subprocess, "run", run)

    result = service_manager.get_service_status("openhab.service")

    assert result["active"]
    assert result["status"] == "active"
    assert result["uptime_str"] == "Mon 2026-11-02 10:00:00 CET"
    assert result["last_run_str"] is None
    run.assert_called_once_with(
        [
            "systemctl",
            "show",
            "openhab.service",
            "--property=LoadState,ActiveState,ActiveEnterTimestamp,"
            "StateChangeTimestamp,InactiveEnterTimestamp",
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )


def test_service_status_preserves_inactive_time_and_not_found_state(monkeypatch):
    run = Mock(
        return_value=Mock(
            returncode=0,
            stdout=(
                "LoadState=loaded\n"
                "ActiveState=inactive\n"
                "ActiveEnterTimestamp=\n"
                "StateChangeTimestamp=Mon 2026-11-02 10:00:00 CET\n"
                "InactiveEnterTimestamp=Mon 2026-11-02 10:00:00 CET\n"
            ),
            stderr="",
        )
    )
    monkeypatch.setattr(service_manager.subprocess, "run", run)

    inactive = service_manager.get_service_status("evcc.service")

    assert not inactive["active"]
    assert inactive["status"] == "inactive"
    assert inactive["last_run_str"] == "Mon 2026-11-02 10:00:00 CET"

    run.return_value.stdout = "LoadState=not-found\nActiveState=inactive\n"
    missing = service_manager.get_service_status("evcc.service")

    assert not missing["active"]
    assert missing["status"] == "not-found"
