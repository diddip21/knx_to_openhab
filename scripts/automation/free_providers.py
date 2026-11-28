"""Reviewed, strictly free provider routes; catalog data never grants execution rights."""

import json
import os
import urllib.request
from decimal import Decimal, InvalidOperation

OPENROUTER_MODELS = (
    "openrouter/nvidia/nemotron-3-ultra-550b-a55b:free",
    "openrouter/nvidia/nemotron-3.5-lightning:free",
    "openrouter/google/gemma-4-31b-it:free",
)
MAX_CATALOG_BYTES = 4_000_000


def guard_config() -> dict:
    body = {
        "provider": {
            "max_price": {"prompt": 0, "completion": 0, "request": 0, "image": 0, "audio": 0},
            "zdr": True,
            "data_collection": "deny",
            "require_parameters": True,
            "allow_fallbacks": True,
        },
        "plugins": [],
    }
    return {
        "providers": {
            "openrouter": {
                "body": body,
                "models": {
                    name.split("/", 1)[1]: {"body": {**body, "models": [name.split("/", 1)[1]]}}
                    for name in OPENROUTER_MODELS
                },
            }
        }
    }


def credentials(environment: dict, model: str | None) -> dict:
    """Add only the explicitly selected provider key and a controller-built policy."""
    if model in OPENROUTER_MODELS:
        key = os.environ.get("OPENROUTER_API_KEY", "")
        if key:
            environment["OPENROUTER_API_KEY"] = key
        environment["OPENCODE_CONFIG_CONTENT"] = json.dumps(guard_config())
    return environment


def eligible_catalog(data: object) -> set[str]:
    if not isinstance(data, dict) or not isinstance(data.get("data"), list):
        return set()
    found = set()
    for model in data["data"]:
        if not isinstance(model, dict):
            continue
        name = "openrouter/" + str(model.get("id", ""))
        price = model.get("pricing")
        if name not in OPENROUTER_MODELS or not isinstance(price, dict):
            continue
        try:
            zero = all(
                not isinstance(price.get(field), bool)
                and Decimal(str(price[field])).is_finite()
                and Decimal(str(price[field])) == 0
                for field in {"prompt", "completion", *price}
                if field != "discount"
            )
        except (InvalidOperation, KeyError, ValueError):
            continue
        context = model.get("context_length")
        if (
            zero
            and "tools" in (model.get("supported_parameters") or [])
            and type(context) is int
            and context >= 65536
        ):
            found.add(name)
    return found


def discover(diagnostics: dict) -> set[str]:
    diagnostics.update(status="not_configured", approved_count=0)
    if not os.environ.get("OPENROUTER_API_KEY"):
        return set()
    try:
        request = urllib.request.Request(
            "https://openrouter.ai/api/v1/models", headers={"Accept": "application/json"}
        )
        with urllib.request.urlopen(request, timeout=15) as response:
            raw = response.read(MAX_CATALOG_BYTES + 1)
        if len(raw) > MAX_CATALOG_BYTES:
            raise ValueError
        models = eligible_catalog(json.loads(raw))
        diagnostics.update(status="catalog_ready", approved_count=len(models))
        return models
    except (OSError, ValueError, TypeError, RecursionError):
        diagnostics["status"] = "catalog_unavailable"
        return set()
