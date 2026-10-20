"""The package update UI must never install arbitrary names or unrelated packages."""

import base64
import secrets
import subprocess
from pathlib import Path
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
            return completed(args, "install ok installed\t5.0.0-1")
        if args[0] == "apt-cache":
            return completed(args, "openhab:\n  Installed: 5.0.0-1\n  Candidate: 5.1.0-1\n")
        return completed(args)

    monkeypatch.setattr(service_updates, "_command", run)
    data = service_updates.package_version("openhab")
    assert data["installed"] == "5.0.0-1"
    assert data["candidate"] == "5.1.0-1"
    assert data["update_available"] is True
    assert commands[-1] == ["dpkg", "--compare-versions", "5.1.0-1", "gt", "5.0.0-1"]
    assert commands[0] == [
        "dpkg-query",
        "-W",
        "-f=${Status}\\t${Version}",
        "--",
        "openhab",
    ]


def test_removed_package_with_residual_config_is_not_supported(monkeypatch):
    calls = []

    def run(args, timeout=10):
        calls.append(args)
        return completed(args, "deinstall ok config-files\t5.0.0-1")

    monkeypatch.setattr(service_updates, "_command", run)
    data = service_updates.package_version("openhab")

    assert data["supported"] is False
    assert data["installed"] is None
    assert calls == [["dpkg-query", "-W", "-f=${Status}\\t${Version}", "--", "openhab"]]


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
    assert "timeout" not in calls[0][1]


def test_package_list_refresh_fails_on_any_repository_error():
    repo_root = Path(__file__).resolve().parents[1]
    helper = (repo_root / "installer" / "service_update.sh").read_text(encoding="utf-8")
    assert "/usr/bin/apt-get update --error-on=any" in helper


def test_changed_candidate_is_rejected_before_start(monkeypatch):
    monkeypatch.setattr(
        service_updates,
        "package_version",
        lambda _: {"supported": True, "update_available": True, "candidate": "5.2.0-1"},
    )
    updater = service_updates.ServiceUpdates()
    assert updater.start("openhab", "5.1.0-1")[0] is False
    assert updater.status()["state"] == "idle"


def auth_header(username, password):
    encoded = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
    return {"Authorization": f"Basic {encoded}"}


@pytest.fixture
def auth_credentials(monkeypatch):
    if not app_module.FLASK_AVAILABLE:
        pytest.skip("Flask unavailable")
    default_password = app_module.cfg.get("auth", {}).get("password")
    username = f"test-{secrets.token_hex(8)}"
    password = secrets.token_urlsafe(24)
    monkeypatch.setitem(
        app_module.cfg,
        "auth",
        {"enabled": True, "user": username, "password": password},
    )
    return {"username": username, "password": password, "default_password": default_password}


@pytest.fixture
def client(auth_credentials):
    app_module.app.testing = True
    return app_module.app.test_client()


def test_api_requires_auth_and_request_header(client, auth_credentials, monkeypatch):
    start = Mock(return_value=(True, "started"))
    monkeypatch.setattr(app_module.service_updates, "start", start)
    url = "/api/service/updates/evcc"
    assert client.post(url).status_code == 401
    headers = auth_header(auth_credentials["username"], auth_credentials["password"])
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


def test_api_rejects_default_password_and_unlisted_package(client, auth_credentials, monkeypatch):
    start = Mock()
    monkeypatch.setattr(app_module.service_updates, "start", start)
    headers = {
        **auth_header(auth_credentials["username"], auth_credentials["password"]),
        "X-Requested-With": "XMLHttpRequest",
    }
    assert client.post("/api/service/updates/ssh", headers=headers).status_code == 404
    default_password = auth_credentials["default_password"] or ""
    monkeypatch.setitem(app_module.cfg["auth"], "password", default_password)
    default_headers = {
        **auth_header(auth_credentials["username"], default_password),
        "X-Requested-With": "XMLHttpRequest",
    }
    assert client.post("/api/service/updates/openhab", headers=default_headers).status_code == 403
    start.assert_not_called()
