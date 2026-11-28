"""Classify private provider errors into fixed, controller-owned decisions."""

import json


def classify(error: object) -> dict:
    data = error if isinstance(error, dict) else {}
    nested = data.get("data")
    nested = nested if isinstance(nested, dict) else {}
    status = nested.get("statusCode", data.get("statusCode", data.get("status")))
    status = status if type(status) is int and 100 <= status <= 599 else 0
    private = json.dumps(error).casefold()
    if status in {401, 403} or any(
        term in private for term in ("unauthorized", "authentication", "api key", "credential")
    ):
        code = "auth"
    elif any(
        term in private
        for term in (
            "daily",
            "per day",
            "today",
            "account limit",
            "global limit",
            "shared quota",
            "balance",
            "credits exhausted",
        )
    ):
        code = "shared_limit"
    elif status == 413 or any(
        term in private for term in ("too large", "too long", "context length", "tokens per")
    ):
        code = "request_size"
    elif status == 429 or any(
        term in private for term in ("rate limit", "rate_limit", "ratelimit")
    ):
        code = "rate_limit"
    elif any(term in private for term in ("quota", "usage limit", "freeusage")):
        code = "shared_limit"
    else:
        code = "provider_error"
    return {"provider_failure": code, "provider_http_status": status}


def permits_fallback(metrics: dict) -> bool:
    return metrics.get("provider_failure") not in {"auth", "shared_limit", "request_size"}
