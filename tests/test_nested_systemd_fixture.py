"""Portable phase dispatch tests; never provision or contact a manager."""

import pytest

from scripts import nested_systemd_fixture as fixture


def test_invalid_phase_has_no_guard_or_application_effect(monkeypatch):
    calls = []
    monkeypatch.setattr(fixture, "require_guest", lambda nonce: calls.append("guard"))
    with pytest.raises(ValueError):
        fixture.run_phase("host-install", "nonce")
    assert calls == []


def test_fixture_refusal_precedes_application_effect(monkeypatch):
    calls = []

    def refuse(nonce):
        raise ValueError("wrong guest")

    monkeypatch.setattr(fixture, "require_guest", refuse)
    monkeypatch.setattr(fixture, "bootstrap", lambda nonce: calls.append("bootstrap"))
    with pytest.raises(ValueError, match="wrong guest"):
        fixture.run_phase("bootstrap", "nonce")
    assert calls == []
