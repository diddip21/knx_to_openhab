"""The package update UI must never install arbitrary names or unrelated packages."""

import subprocess
from unittest.mock import Mock

import pytest

from web_ui.backend import app as app_module
from web_ui.backend import service_updates


def completed(args, output="", code=0):
    return subprocess.CompletedProcess(args, code, output, "")


def test_package_comparison_uses_apt_candidate_and_dpkg_order(monkeypatch):
    commands = []

    def run(args, timeout=10):
        commands.append(args)
        if args[0] == "dpkg-query":
            return completed(args, "5.0.0-1")
        if args[0] == "apt-cache":
            return completed(args, "openhab:\n  Installed: 5.0.0-1\n  Candidate: 5.1.0-1\n")
        return completed(args)

    monkeypatch.setattr(service_updates, "_command", run)
    data = service_updates.package_version("openhab")
    assert data["installed"] == "5.0.0-1"
    assert data["candidate"] == "5.1.0-1"
    assert data["update_available"] is True
    assert commands[-1] == ["dpkg", "--compare-versions", "5.1.0-1", "gt", "5.0.0-1"]


@pytest.mark.parametrize("pkg", ["evcc", "openhab"])
def test_non_apt_service_cannot_update(monkeypatch, pkg):
    monkeypatch.setattr(
        service_updates, "_command", lambda args, timeout=10: completed(args, code=1)
    )
    assert service_updates.package_version(pkg)["supported"] is False


def test_unknown_service_never_runs_command(monkeypatch):
    monkeypatch.setattr(service_updates, "_command", Mock(side_effect=AssertionError("invoked")))
    with pytest.raises(ValueError):
        service_updates.package_version("ssh")
    assert service_updates.ServiceUpdates().start("ssh") == (False, "Unsupported action.")


def test_update_worker_invokes_only_fixed_helper(monkeypatch):
    calls = []

    def run(args, **kwargs):
        calls.append((args, kwargs))
        return completed(args)

    monkeypatch.setattr(service_updates.subprocess, "run", run)
    updater = service_updates.ServiceUpdates()
    updater._run("evcc", "0.205.1")
    assert updater.status()["state"] == "completed"
    assert calls[0][0] == ["sudo", "-n", service_updates.HELPER, "evcc"]
    assert calls[0][1]["input"] == "0.205.1\n"
    assert calls[0][1]["timeout"] == 900


def test_changed_candidate_is_rejected_before_start(monkeypatch):
    monkeypatch.setattr(
        service_updates,
        "package_version",
        lambda _: {"supported": True, "update_available": True, "candidate": "5.2.0-1"},
    )
    updater = service_updates.ServiceUpdates()
    assert updater.start("openhab", "5.1.0-1")[0] is False
    assert updater.status()["state"] == "idle"


@pytest.fixture
def client(monkeypatch):
    if not app_module.FLASK_AVAILABLE:
        pytest.skip("Flask unavailable")
    monkeypatch.setitem(
        app_module.cfg, "auth", {"enabled": True, "user": "test", "password": "secret"}
    )
    app_module.app.testing = True
    return app_module.app.test_client()


def test_api_requires_auth_and_request_header(client, monkeypatch):
    start = Mock(return_value=(True, "started"))
    monkeypatch.setattr(app_module.service_updates, "start", start)
    url = "/api/service/updates/evcc"
    assert client.post(url).status_code == 401
    headers = {"Authorization": "Basic dGVzdDpzZWNyZXQ="}
    assert client.post(url, headers=headers).status_code == 403
    assert (
        client.post(
            url,
            headers={**headers, "X-Requested-With": "XMLHttpRequest"},
            json={"version": "0.205.1"},
        ).status_code
        == 202
    )
    start.assert_called_once_with("evcc", "0.205.1")


def test_api_rejects_default_password_and_unlisted_package(client, monkeypatch):
    start = Mock()
    monkeypatch.setattr(app_module.service_updates, "start", start)
    headers = {"Authorization": "Basic dGVzdDpzZWNyZXQ=", "X-Requested-With": "XMLHttpRequest"}
    assert client.post("/api/service/updates/ssh", headers=headers).status_code == 404
    monkeypatch.setitem(app_module.cfg["auth"], "password", "logihome")
    headers["Authorization"] = "Basic dGVzdDpsb2dpaG9tZQ=="
    assert client.post("/api/service/updates/openhab", headers=headers).status_code == 403
    start.assert_not_called()
