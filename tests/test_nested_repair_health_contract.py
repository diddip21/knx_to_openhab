"""Portable contract regression for the observed installed-repair readiness blocker."""

import json
from types import SimpleNamespace

import pytest

from scripts import nested_fixture_repair as repair


def test_repair_readiness_requests_the_public_api_health_endpoint(monkeypatch):
    from installer.update_core import transaction

    requested = []

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, limit):
            return b'{"status":"ready","version":"0.1.0"}'

    def open_request(url, *, timeout):
        requested.append(url)
        return Response()

    monkeypatch.setattr(
        transaction.urllib.request,
        "build_opener",
        lambda *handlers: SimpleNamespace(open=open_request),
    )
    repair.health()

    # Production exempts /api/health from auth. /health redirects to login;
    # following that redirect would not establish actual application readiness.
    assert requested == ["http://127.0.0.1:8085/api/health"]


@pytest.mark.parametrize(
    "body", [b"{}", b'{"status":"not_ready"}', b'{"status":"ready","version":"9.9.9"}']
)
def test_readiness_requires_ready_json_and_exact_installed_version(monkeypatch, body):
    from installer.update_core import transaction

    monkeypatch.setattr(transaction, "fetch_health", lambda *a: json.loads(body))
    with pytest.raises(ValueError, match="readiness"):
        repair.health()


def test_shared_production_health_url_is_an_actual_public_application_route(monkeypatch):
    from urllib.parse import urlsplit

    from installer.update_core.transaction import health_url
    from web_ui.backend import app as app_module

    monkeypatch.setitem(app_module.cfg, "auth", {"enabled": True})
    monkeypatch.setattr(app_module, "_sessions", lambda: pytest.fail("must remain public"))
    response = app_module.app.test_client().get(urlsplit(health_url({})).path)
    assert response.status_code == 200
    assert response.get_json() == {"status": "ready", "version": "0.1.0"}


def test_readiness_transport_refuses_redirect_without_fallback(monkeypatch):
    from installer.update_core import transaction

    requested = []

    def build_opener(proxy, redirects):
        assert proxy.proxies == {}

        def open_request(url, *, timeout):
            requested.append(url)
            return redirects.redirect_request(None, None, 302, "Found", {}, "/login")

        return SimpleNamespace(open=open_request)

    monkeypatch.setattr(transaction.urllib.request, "build_opener", build_opener)
    with pytest.raises(ValueError, match="redirect"):
        repair.health()
    assert requested == [transaction.health_url({})]
