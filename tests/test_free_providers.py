"""Strict price, task fallback and credential-boundary regression tests."""

import json

import pytest

from scripts.automation import free_providers as free
from scripts.automation.provider_policy import fallback_model


def candidate(**changes):
    return {
        "id": free.OPENROUTER_MODELS[0].split("/", 1)[1],
        "context_length": 100000,
        "supported_parameters": ["tools"],
        "pricing": {"prompt": "0", "completion": "0"},
        **changes,
    }


def test_exact_reviewed_free_model_with_tools_and_zero_prices_is_eligible():
    assert free.eligible_catalog({"data": [candidate()]}) == {free.OPENROUTER_MODELS[0]}


@pytest.mark.parametrize(
    "price",
    [
        {"prompt": "0.001", "completion": "0"},
        {"prompt": "0", "completion": "0", "request": "1"},
        {"prompt": "0"},
        {"prompt": True, "completion": 0},
        {"prompt": "NaN", "completion": 0},
    ],
)
def test_nonzero_unknown_missing_or_invalid_price_never_qualifies(price):
    assert not free.eligible_catalog({"data": [candidate(pricing=price)]})


@pytest.mark.parametrize(
    "changes",
    [
        {"id": "vendor/unknown:free"},
        {"id": "nvidia/paid"},
        {"context_length": 1000},
        {"context_length": "100000"},
        {"supported_parameters": []},
        {"supported_parameters": "tools"},
        {"supported_parameters": 42},
    ],
)
def test_catalog_claim_cannot_expand_eligibility(changes):
    assert not free.eligible_catalog({"data": [candidate(**changes)]})


def test_missing_key_is_optional_without_network_request(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setattr(free.urllib.request, "urlopen", lambda *a, **k: pytest.fail("No request"))
    info = {}
    assert free.discover(info) == set()
    assert info["status"] == "not_configured"


def test_only_selected_provider_receives_its_key_and_zero_cost_policy(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-private-key")
    assert free.credentials({}, "opencode/hy4-flash-free") == {}
    result = free.credentials({}, free.OPENROUTER_MODELS[0])
    assert result["OPENROUTER_API_KEY"] == "test-private-key"
    config = json.loads(result["OPENCODE_CONFIG_CONTENT"])
    assert "test-private-key" not in result["OPENCODE_CONFIG_CONTENT"]
    for model in config["providers"]["openrouter"]["models"].values():
        body = model["body"]
        assert all(value == 0 for value in body["provider"]["max_price"].values())
        assert body["provider"]["zdr"] and body["provider"]["data_collection"] == "deny"
        assert body["plugins"] == []


@pytest.mark.parametrize("failure", ["auth", "shared_limit"])
def test_provider_failure_skips_other_models_on_same_account(failure):
    models = ["opencode/a-free", "opencode/b-free", free.OPENROUTER_MODELS[0]]
    assert (
        fallback_model(models, models[0], {models[0]}, {"provider_failure": failure}) == models[2]
    )
    assert fallback_model(models[:2], models[0], {models[0]}, {"provider_failure": failure}) is None
