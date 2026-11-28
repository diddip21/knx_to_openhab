"""Classify private provider errors into fixed, controller-owned decisions."""

import json
import math


def classify(error: object) -> dict:
    data = error if isinstance(error, dict) else {}
    nested = data.get("data")
    nested = nested if isinstance(nested, dict) else {}
    status = nested.get(
        "statusCode", nested.get("status", data.get("statusCode", data.get("status")))
    )
    status = status if type(status) is int and 100 <= status <= 599 else 0
    private = json.dumps(error).casefold()
    kind = data.get("type")
    delay = data.get("retryAfterMs", nested.get("retryAfterMs"))
    retry = (
        math.ceil(delay / 1000)
        if isinstance(delay, (int, float))
        and not isinstance(delay, bool)
        and 0 <= delay <= 604_800_000
        else 0
    )
    if (
        kind == "provider.auth"
        or status in {401, 403}
        or any(
            term in private for term in ("unauthorized", "authentication", "api key", "credential")
        )
    ):
        code = "auth"
    elif any(
        term in private
        for term in (
            "account limit",
            "global limit",
            "shared quota",
            "balance",
            "credits exhausted",
        )
    ):
        code = "shared_limit"
    elif kind in {"provider.free-limit", "provider.model-budget-limit"}:
        # The pinned CLI explicitly recommends switching models for these
        # model allowances. Never rotate accounts or credentials.
        code = "model_limit"
    elif kind in {"provider.quota", "provider.budget-limit", "provider.go-limit"} or any(
        term in private for term in ("daily", "per day", "today")
    ):
        code = "shared_limit"
    elif status == 413 or any(
        term in private for term in ("too large", "too long", "context length", "tokens per")
    ):
        code = "request_size"
    elif (
        kind == "provider.rate-limit"
        or status == 429
        or any(term in private for term in ("rate limit", "rate_limit", "ratelimit"))
    ):
        code = "rate_limit"
    elif any(term in private for term in ("quota", "usage limit", "freeusage")):
        code = "shared_limit"
    else:
        code = "provider_error"
    return {"provider_failure": code, "provider_http_status": status, "retry_after_seconds": retry}


def permits_fallback(metrics: dict) -> bool:
    return metrics.get("provider_failure") not in {"auth", "shared_limit", "request_size"}


def fallback_model(models: list[str], current: str, tried: set[str], metrics: dict) -> str | None:
    """An account failure blocks that provider, not an independent authorized account."""
    failure = metrics.get("provider_failure")
    if failure == "request_size":
        return None
    candidates = [model for model in models if model not in tried]
    independent = [
        model for model in candidates if model.split("/", 1)[0] != current.split("/", 1)[0]
    ]
    if failure in {"auth", "shared_limit"}:
        candidates = independent
    elif failure in {"model_limit", "rate_limit"} or metrics.get("provider_http_status", 0) >= 500:
        candidates = independent or candidates
    return candidates[0] if candidates else None
