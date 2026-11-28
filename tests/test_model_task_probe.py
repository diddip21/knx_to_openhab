"""Independent correctness checks and malformed/untrusted model answers."""

import json

import pytest

from scripts.automation import provider_policy, task_probe


@pytest.mark.parametrize(
    "task,answer",
    [
        (
            "plan",
            {
                "default_count": 1,
                "preserves_false": True,
                "rejects_bool": True,
                "flow": ["config", "api", "generation", "legacy", "yaml"],
            },
        ),
        (
            "implement",
            {
                "expression": "1 if value is None else value if type(value) is int and value > 0 else None"
            },
        ),
        ("repair", {"expression": "index < 0 or index >= len(values)"}),
    ],
)
def test_task_correctness(task, answer):
    result = task_probe.assess("ROUTER_TASK " + json.dumps(answer), task)
    assert result["task_correct"]
    assert result["task_cases_passed"] == result["task_cases_total"]


@pytest.mark.parametrize(
    "source",
    [
        "value or 1",
        "value if type(value) is int else 1",
        "1",
        "__import__('os').system('echo unsafe')",
        "value.__class__",
        "[x for x in value]",
        "len('x')",
        "type(type(value))",
        "int(value)",
        "2 ** 99999999",
    ],
)
def test_incorrect_or_unsafe_expression_fails_without_exposing_source(source):
    result = task_probe.assess("ROUTER_TASK " + json.dumps({"expression": source}), "implement")
    assert not result["task_correct"]
    assert source not in json.dumps(result)


@pytest.mark.parametrize(
    "answer",
    ["", "ROUTER_TASK []", "ROUTER_TASK null", "ROUTER_TASK {", "ROUTER_TASK {}\nROUTER_TASK {}"],
)
def test_malformed_answers_fail_closed(answer):
    assert not task_probe.assess(answer, "plan")["task_correct"]


def test_off_by_one_repair_is_rejected():
    wrong = {"expression": "index < 0 or index > len(values)"}
    result = task_probe.assess("ROUTER_TASK " + json.dumps(wrong), "repair")
    assert not result["task_correct"] and result["task_cases_passed"] < 6


def test_plan_preserves_meaning_across_casing_and_an_extra_ui_stage():
    answer = {
        "default_count": 1,
        "preserves_false": True,
        "rejects_bool": True,
        "flow": ["UI", "config", "API", "generation", "Legacy", "YAML"],
    }
    assert task_probe.assess("ROUTER_TASK " + json.dumps(answer), "plan")["task_correct"]
    answer["preserves_false"] = False
    assert not task_probe.assess("ROUTER_TASK " + json.dumps(answer), "plan")["task_correct"]


@pytest.mark.parametrize(
    "error,code,allowed",
    [
        ({"status": 401}, "auth", False),
        ({"data": {"statusCode": 403}}, "auth", False),
        ({"message": "private daily rate limit"}, "shared_limit", False),
        ({"message": "private shared quota"}, "shared_limit", False),
        ({"message": "private account limit"}, "shared_limit", False),
        ({"message": "private quota exceeded"}, "shared_limit", False),
        ({"statusCode": 413}, "request_size", False),
        ({"message": "private context length exceeded"}, "request_size", False),
        ({"status": 429}, "rate_limit", True),
        ({"message": "private model rate_limit"}, "rate_limit", True),
        ({"statusCode": 503}, "provider_error", True),
    ],
)
def test_provider_policy_does_not_cycle_shared_limits_or_leak_errors(error, code, allowed):
    result = provider_policy.classify(error)
    assert result["provider_failure"] == code
    assert provider_policy.permits_fallback(result) is allowed
    assert "private" not in json.dumps(result)


@pytest.mark.parametrize(
    "kind,code,allowed",
    [
        ("provider.auth", "auth", False),
        ("provider.free-limit", "model_limit", True),
        ("provider.model-budget-limit", "model_limit", True),
        ("provider.budget-limit", "shared_limit", False),
        ("provider.quota", "shared_limit", False),
        ("provider.go-limit", "shared_limit", False),
        ("provider.rate-limit", "rate_limit", True),
    ],
)
def test_pinned_v2_error_types_and_server_cooldown(kind, code, allowed):
    result = provider_policy.classify({"type": kind, "status": 429, "retryAfterMs": 120_001})
    assert result["provider_failure"] == code
    assert result["retry_after_seconds"] == 121
    assert result["provider_http_status"] == 429
    assert provider_policy.permits_fallback(result) is allowed


@pytest.mark.parametrize("delay", [True, "60000", -1, float("inf"), float("nan"), 10**30])
def test_invalid_retry_delays_are_not_trusted(delay):
    assert provider_policy.classify({"retryAfterMs": delay})["retry_after_seconds"] == 0


def test_explicit_model_scope_and_account_scope_take_precedence_over_generic_429():
    assert (
        provider_policy.classify(
            {"type": "provider.free-limit", "status": 429, "message": "model daily allowance used"}
        )["provider_failure"]
        == "model_limit"
    )
    assert (
        provider_policy.classify(
            {"type": "provider.free-limit", "status": 429, "message": "account limit reached"}
        )["provider_failure"]
        == "shared_limit"
    )
