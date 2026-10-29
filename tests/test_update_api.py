"""Existing authenticated updater API contracts (no visual UI changes)."""

from unittest.mock import Mock

import pytest

from web_ui.backend import app as app_module

REAL_MUTATE = app_module._mutate


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setattr(app_module, "cfg", {"auth": {"enabled": False}})
    monkeypatch.setattr(app_module.sys, "platform", "linux")
    monkeypatch.setattr(app_module, "_mutate", lambda fn, *a, **k: fn(*a, **k))
    updater = Mock()
    updater.trigger_update.return_value = (True, "Accepted, not completed")
    updater.last_update_request_id = "10000000-0000-4000-8000-000000000001"
    monkeypatch.setattr(app_module, "updater", updater)
    return app_module.app.test_client(), updater


@pytest.mark.parametrize(
    "body,expected", [(None, "stable"), ({}, "stable"), ({"channel": "prerelease"}, "prerelease")]
)
def test_compatible_submission(api, body, expected):
    client, updater = api
    response = client.post("/api/version/update", **({} if body is None else {"json": body}))
    assert response.status_code == 200
    assert response.json == {
        "status": "updating",
        "message": "Accepted, not completed",
        "request_id": updater.last_update_request_id,
    }
    updater.trigger_update.assert_called_once_with(
        **({} if expected == "stable" else {"channel": expected})
    )


@pytest.mark.parametrize(
    "raw",
    [
        "null",
        "[]",
        '{"channel":null}',
        '{"channel":"beta"}',
        '{"url":"https://evil"}',
        '{"channel":"stable","channel":"prerelease"}',
        "{",
        " ",
    ],
)
def test_bad_input_before_even_windows_simulation(api, monkeypatch, raw):
    client, updater = api
    monkeypatch.setattr(app_module.sys, "platform", "win32")
    response = client.post("/api/version/update", data=raw, content_type="application/json")
    assert response.status_code == 400
    updater.trigger_update.assert_not_called()


def test_non_json_body_invalid(api):
    client, updater = api
    assert client.post("/api/version/update", data="channel=stable").status_code == 400
    updater.trigger_update.assert_not_called()


def test_oversized_body_is_400_before_submission(api):
    client, updater = api
    assert (
        client.post(
            "/api/version/update", data=b" " * 4097, content_type="application/json"
        ).status_code
        == 400
    )
    updater.trigger_update.assert_not_called()


def test_valid_windows_request_still_simulates_without_effects(api, monkeypatch):
    client, updater = api
    monkeypatch.setattr(app_module.sys, "platform", "win32")
    response = client.post("/api/version/update", json={"channel": "prerelease"})
    assert response.status_code == 200 and response.json["status"] == "simulated"
    updater.trigger_update.assert_not_called()


def test_busy_and_error_messages_preserved(api):
    client, updater = api
    updater.trigger_update.return_value = (False, "Another update is active")
    updater.last_update_status = "busy"
    response = client.post("/api/version/update")
    assert response.status_code == 409 and response.json["error"] == "Another update is active"
    updater.last_update_status = "failed"
    updater.trigger_update.return_value = (False, "Run verified administrator bootstrap")
    response = client.post("/api/version/update")
    assert response.status_code == 500 and "verified" in response.json["error"]


def test_legacy_tuple_failure_message_is_not_replaced_by_error_code_lookup(api, monkeypatch):
    from types import SimpleNamespace

    client, _ = api
    monkeypatch.setattr(
        app_module, "updater", SimpleNamespace(trigger_update=lambda: (False, "original failure"))
    )
    response = client.post("/api/version/update")
    assert response.status_code == 500 and response.json == {"error": "original failure"}


def test_update_keeps_existing_mutation_lease(api, monkeypatch):
    from contextlib import contextmanager

    client, updater = api
    monkeypatch.setattr(app_module, "_mutate", REAL_MUTATE)

    @contextmanager
    def denied(_paths):
        raise app_module.MaintenanceError("maintenance")
        yield

    monkeypatch.setattr(app_module, "mutation_lease", denied)
    assert client.post("/api/version/update").status_code == 503
    updater.trigger_update.assert_not_called()


def test_update_requires_auth_and_csrf(api, monkeypatch, tmp_path):
    from web_ui.backend.auth import hash_password

    client, updater = api
    monkeypatch.setattr(
        app_module,
        "cfg",
        {
            "auth": {
                "enabled": True,
                "user": "operator",
                "password_hash": hash_password("test-only-password"),
            },
            "sessions_file": str(tmp_path / "sessions.sqlite3"),
        },
    )
    monkeypatch.setattr(app_module, "_session_store", None)
    monkeypatch.setattr(app_module, "get_session_secret", lambda *a: b"k" * 32)
    assert client.post("/api/version/update").status_code == 401
    client.get("/login")
    response = client.post(
        "/login",
        data={
            "csrf_token": client.get_cookie("knx_login_csrf").value,
            "username": "operator",
            "password": "test-only-password",
        },
    )
    assert response.status_code == 302
    assert client.post("/api/version/update").status_code == 403
    updater.trigger_update.assert_not_called()
    assert (
        client.post(
            "/api/version/update", headers={"X-CSRF-Token": client.get_cookie("knx_csrf").value}
        ).status_code
        == 200
    )


def test_release_check_channel_validation(api):
    client, updater = api
    updater.check_for_updates.return_value = {"update_available": False}
    assert client.get("/api/version/check?channel=beta").status_code == 400
    updater.check_for_updates.assert_not_called()
    assert client.get("/api/version/check?channel=prerelease").status_code == 200
    updater.check_for_updates.assert_called_once_with(channel="prerelease")


def test_schema_describes_submission_compatibility_and_errors():
    import json
    from pathlib import Path

    schema = json.loads((Path(__file__).parents[1] / "web_ui/api_schema.json").read_text())
    operation = schema["paths"]["/api/version/update"]["post"]
    assert operation["requestBody"]["required"] is False
    body = operation["requestBody"]["content"]["application/json"]["schema"]
    assert body["additionalProperties"] is False
    assert body["properties"]["channel"]["enum"] == ["stable", "prerelease"]
    assert {"200", "400", "401", "403", "409", "500", "503"} <= set(operation["responses"])


def test_log_preserves_string_and_adds_protected_request_status(api):
    client, updater = api
    updater.get_update_log.return_value = "checking: Waiting for readiness\n"
    updater.get_update_status.return_value = {
        "request_id": updater.last_update_request_id,
        "phase": "checking",
        "message": "Waiting for readiness",
        "outcome": "running",
    }
    response = client.get("/api/version/log")
    assert response.json == {
        "log": "checking: Waiting for readiness\n",
        "update": updater.get_update_status.return_value,
    }
