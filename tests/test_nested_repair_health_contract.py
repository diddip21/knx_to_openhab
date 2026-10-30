"""Portable contract regression for the observed installed-repair readiness blocker."""

from types import SimpleNamespace

import pytest

from scripts import nested_fixture_repair as repair


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="Known 829992f repair runner requests /health; real installed request returned HTTP 302",
)
def test_repair_readiness_requests_the_public_api_health_endpoint(monkeypatch):
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
        repair.urllib.request,
        "build_opener",
        lambda *handlers: SimpleNamespace(open=open_request),
    )
    repair.health()

    # Production exempts /api/health from auth. /health redirects to login;
    # following that redirect would not establish actual application readiness.
    assert requested == ["http://127.0.0.1:8085/api/health"]
