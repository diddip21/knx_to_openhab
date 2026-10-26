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
