"""Unit tests for the approved-free-model OpenCode router."""

import importlib.util
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "opencode_model_router.py"
SPEC = importlib.util.spec_from_file_location("opencode_model_router", SCRIPT)
assert SPEC and SPEC.loader
router = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(router)


def events(text="ROUTER_OK\nknx_to_openhab supports legacy and yaml.", task="plan"):
    """Include genuinely completed skill/read tool calls."""
    payloads = {
        "plan": {
            "default_count": 1,
            "preserves_false": True,
            "rejects_bool": True,
            "flow": ["config", "api", "generation", "legacy", "yaml"],
        },
        "implement": {
            "expression": "1 if value is None else value if type(value) is int and value > 0 else None"
        },
        "repair": {"expression": "index < 0 or index >= len(values)"},
    }
    text += "\nROUTER_TASK " + json.dumps(payloads[task])
    return "\n".join(
        json.dumps(event)
        for event in [
            {
                "type": "tool_use",
                "part": {"tool": "skill", "state": {"status": "completed"}},
            },
            {
                "type": "tool_use",
                "part": {"tool": "read", "state": {"status": "completed"}},
            },
            {"type": "text", "part": {"text": text}},
        ]
    )


def test_allowlisted_free_ids_only():
    found = router.parse_catalog(
        "\n".join(
            [
                "opencode/hy4-flash-free",
                "opencode/deepseek-v4.1-flash-free",
                "opencode/some-unknown-free",
                "opencode/glm-5.3-flash",
                "openai/gpt-6",
                "not-opencode/foo-free",
                "opencode/hy4-flash-free --some flag",
            ]
        )
    )
    assert "opencode/hy4-flash-free" in found
    assert "opencode/deepseek-v4.1-flash-free" in found
    assert "opencode/glm-5.3-flash" not in found
    assert "openai/gpt-6" not in found
    assert "opencode/hy4-flash-free --some flag" not in found
    assert "opencode/some-unknown-free" in found
    assert set(router.APPROVED_FREE_MODELS) == {
        "opencode/hy4-flash-free",
        "opencode/deepseek-v4.1-flash-free",
    }


def test_probe_requires_completed_read_and_skill():
    result = router.inspect_events(events(), "plan", 12)
    assert result["passed"] is True
    assert result["read_ok"] is True
    assert result["skill_ok"] is True
    assert result["factual"] is True
    assert result["score"] > 0


@pytest.mark.parametrize("task", router.TASKS)
def test_correct_task_probe_can_pass_for_each_stage(task):
    assert router.inspect_events(events(task=task), task, 20)["passed"]


def test_fast_wrong_task_answer_cannot_beat_correct_slow_answer():
    wrong = events(task="repair")
    failed = router.inspect_events(wrong, "implement", 1)
    passed = router.inspect_events(events(task="implement"), "implement", 90)
    assert failed["passed"] is False and failed["score"] == 0
    assert passed["passed"] and passed["score"] > 0


def test_factual_quality_outweighs_entire_speed_bonus():
    fast = router.inspect_events(events(text="ROUTER_OK"), "plan", 1)
    slow = router.inspect_events(events(), "plan", 100)
    assert fast["passed"] and slow["passed"]
    assert slow["score"] > fast["score"]


@pytest.mark.parametrize(
    "value",
    [
        "ROUTER_OK\nknx_to_openhab supports legacy and yaml.",
        "I can use the skill tool. ROUTER_OK",
        "Invalid tools",
    ],
)
def test_model_answer_without_tools_does_not_pass(value):
    data = json.dumps({"type": "text", "part": {"text": value}})
    assert router.inspect_events(data, "plan", 4)["passed"] is False


def test_tool_failure_does_not_pass():
    data = events().replace('"status": "completed"', '"status": "error"', 1)
    assert router.inspect_events(data, "implement", 3)["passed"] is False


def test_missing_marker_does_not_pass():
    data = events("Project knx_to_openhab supports legacy and yaml.")
    assert router.inspect_events(data, "plan", 5)["passed"] is False


def test_rank_success_over_speed():
    a = {"model": router.APPROVED_FREE_MODELS[0], "passed": True, "score": 80}
    b = {"model": router.APPROVED_FREE_MODELS[1], "passed": False, "score": 1000}
    assert router.choose_model([a, b]) is a


def test_rank_quality_and_stable_tie_breaker():
    a = {"model": router.APPROVED_FREE_MODELS[0], "passed": True, "score": 91}
    b = {"model": router.APPROVED_FREE_MODELS[1], "passed": True, "score": 95}
    assert router.choose_model([a, b]) is b
    b["score"] = 91
    assert router.choose_model([b, a]) is a


def test_no_free_model_fails_closed():
    with pytest.raises(RuntimeError, match="No approved free model"):
        router.choose_model([{"model": "openai/gpt-6", "passed": True, "score": 999}])


def test_discovery_intersects_with_allowlist(monkeypatch):
    def fake_run(args, **kwargs):
        assert args == ["opencode", "models", "--standalone"]
        assert kwargs["timeout"] == router.DISCOVERY_TIMEOUT
        return SimpleNamespace(
            returncode=0,
            stdout=("opencode/hy4-flash-free\n" "opencode/fake-free\n" "openai/gpt-6\n"),
        )

    monkeypatch.setattr(router.subprocess, "run", fake_run)
    assert router.discover_models() == {"opencode/hy4-flash-free"}


def test_discovery_fallback_if_first_command_unsupported(monkeypatch):
    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        if len(calls) == 1:
            return SimpleNamespace(returncode=2, stdout="")
        return SimpleNamespace(returncode=0, stdout="opencode/deepseek-v4.1-flash-free\n")

    monkeypatch.setattr(router.subprocess, "run", fake_run)
    assert router.discover_models() == {"opencode/deepseek-v4.1-flash-free"}
    assert calls == [
        ["opencode", "models", "--standalone"],
        ["opencode", "models", "--standalone"],
    ]


def test_probes_are_bounded_and_read_only(monkeypatch):
    def fake_run(args, **kwargs):
        assert "--agent" in args
        assert args[args.index("--agent") + 1] == "ci-smoke"
        assert args[args.index("--model") + 1] == router.APPROVED_FREE_MODELS[0]
        assert kwargs["timeout"] == router.PROBE_TIMEOUT
        assert "GITHUB_TOKEN" not in kwargs["env"]
        return SimpleNamespace(returncode=0, stdout=events(task="implement"))

    monkeypatch.setenv("GITHUB_TOKEN", "a-test-value")
    monkeypatch.setattr(router.subprocess, "run", fake_run)
    result = router.probe_model(router.APPROVED_FREE_MODELS[0], "implement")
    assert result["passed"] is True
    assert result["score"] > 0


def test_failed_probe_is_not_selected(monkeypatch):
    def fake_run(args, **kwargs):
        return SimpleNamespace(returncode=1, stdout="", stderr="rate limited")

    monkeypatch.setattr(router.subprocess, "run", fake_run)
    result = router.probe_model(router.APPROVED_FREE_MODELS[0], "plan")
    assert result["passed"] is False
    assert result["score"] == 0
    assert "rate limited" not in str(result)


def test_no_unapproved_provider_is_ever_probed():
    with pytest.raises(ValueError, match="not approved"):
        router.probe_model("openai/gpt-6", "plan")


def test_prompt_is_bounded_and_has_task_specific_text():
    assert "planning" in router.probe_prompt("plan")
    assert "implementation" in router.probe_prompt("implement")
    with pytest.raises(ValueError):
        router.probe_prompt("merge")


def test_provider_key_is_isolated_from_git_and_other_provider_processes(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "private-test-key")
    monkeypatch.setenv("GITHUB_TOKEN", "private-github-key")
    monkeypatch.setenv("OPENAI_API_KEY", "private-paid-key")
    assert "OPENROUTER_API_KEY" not in router.isolated_environment()
    assert "OPENROUTER_API_KEY" not in router.isolated_environment(router.APPROVED_FREE_MODELS[0])
    result = router.isolated_environment(router.ALL_APPROVED_MODELS[2])
    assert result["OPENROUTER_API_KEY"] == "private-test-key"
    assert "GITHUB_TOKEN" not in result and "OPENAI_API_KEY" not in result


def test_main_exports_only_selected_allowlisted_model(tmp_path, monkeypatch):
    monkeypatch.setattr(
        router, "discover_models", lambda diagnostics=None: set(router.APPROVED_FREE_MODELS)
    )
    monkeypatch.setattr(
        router,
        "probe_model",
        lambda model, task, **kwargs: {
            "model": model,
            "passed": True,
            "factual": True,
            "elapsed_seconds": 4,
            "score": 100 if model == router.APPROVED_FREE_MODELS[1] else 90,
        },
    )
    output = tmp_path / "github-output.txt"
    report = tmp_path / "router-report.json"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.setattr(
        "sys.argv",
        ["opencode_model_router.py", "select", "--task", "plan", "--report", str(report)],
    )
    assert router.main() == 0
    assert output.read_text().strip() == "model=opencode/deepseek-v4.1-flash-free"
    result = json.loads(report.read_text())
    assert result["selected"] == "opencode/deepseek-v4.1-flash-free"
    assert result["ranked"] == list(reversed(router.APPROVED_FREE_MODELS))


def test_main_refuses_all_failed_models(tmp_path, monkeypatch):
    monkeypatch.setattr(
        router, "discover_models", lambda diagnostics=None: set(router.APPROVED_FREE_MODELS)
    )
    monkeypatch.setattr(
        router,
        "probe_model",
        lambda model, task, **kwargs: {"model": model, "passed": False, "score": 0},
    )
    output = tmp_path / "github-output.txt"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.setattr(
        "sys.argv",
        [
            "opencode_model_router.py",
            "select",
            "--task",
            "implement",
            "--report",
            str(tmp_path / "failed.json"),
        ],
    )
    assert router.main() == 1
    assert not output.exists()


PRIVATE = "private-provider-prompt-error-content-must-not-escape"


def configure_main(tmp_path, monkeypatch):
    report = tmp_path / "model.json"
    summary = tmp_path / "summary.md"
    output = tmp_path / "output.txt"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.setattr(
        "sys.argv", ["router", "select", "--task", "implement", "--report", str(report)]
    )
    return report, summary, output


@pytest.mark.parametrize(
    "first",
    ["", "Usage: opencode models\n" + PRIVATE, "other/paid-model\nopencode/unreviewed-free\n"],
)
def test_unusable_discovery_retries_native_command_without_selecting_cache(monkeypatch, first):
    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        return SimpleNamespace(
            returncode=0,
            stdout=first if len(calls) == 1 else router.APPROVED_FREE_MODELS[1] + "\n",
            stderr=PRIVATE,
        )

    monkeypatch.setattr(router.subprocess, "run", fake_run)
    result = router.discover_models()
    assert result == {router.APPROVED_FREE_MODELS[1]}
    assert calls == [["opencode", "models", "--standalone"]] * 2


@pytest.mark.parametrize(
    "catalog,code,attempts",
    [
        ("", "empty_catalog", 2),
        ("Usage: models\n", "empty_catalog", 2),
        ("other/paid-model\nopencode/unreviewed-free\n", "no_approved_models", 2),
    ],
)
def test_main_distinguishes_empty_catalog_from_no_approved_model(
    tmp_path, monkeypatch, capsys, catalog, code, attempts
):
    report, summary, output = configure_main(tmp_path, monkeypatch)
    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        assert args[1] == "models", "No unknown or cached model may be probed"
        return SimpleNamespace(returncode=0, stdout=catalog, stderr=PRIVATE)

    monkeypatch.setattr(router.subprocess, "run", fake_run)
    assert router.main() == 1
    data = json.loads(report.read_text())
    assert data["failure_code"] == code
    assert data["status"] == "failure"
    assert data["selected"] is None
    assert data["probes"] == []
    assert len(data["discovery"]["attempts"]) == attempts
    assert len(calls) == attempts
    assert not output.exists()
    combined = report.read_text() + summary.read_text() + capsys.readouterr().out
    assert PRIVATE not in combined
    assert "other/paid-model" not in combined
    assert "opencode/unreviewed-free" not in combined
    assert code in summary.read_text()


@pytest.mark.parametrize(
    "failure,code",
    [
        ("timeout", "discovery_timeout"),
        ("exit", "discovery_cli_error"),
        ("oserror", "discovery_cli_error"),
    ],
)
def test_discovery_failure_has_two_bounded_attempts_and_fixed_diagnostics(
    tmp_path, monkeypatch, capsys, failure, code
):
    report, summary, output = configure_main(tmp_path, monkeypatch)
    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        assert kwargs["timeout"] == router.DISCOVERY_TIMEOUT
        if failure == "timeout":
            raise subprocess.TimeoutExpired(args, kwargs["timeout"], output=PRIVATE, stderr=PRIVATE)
        if failure == "oserror":
            raise OSError(PRIVATE)
        return SimpleNamespace(returncode=7, stdout=PRIVATE, stderr=PRIVATE)

    monkeypatch.setattr(router.subprocess, "run", fake_run)
    assert router.main() == 1
    data = json.loads(report.read_text())
    assert data["failure_code"] == code
    assert len(calls) == 2
    assert all(attempt["code"] == code for attempt in data["discovery"]["attempts"])
    assert not output.exists()
    captured = capsys.readouterr()
    assert PRIVATE not in report.read_text() + summary.read_text() + captured.out + captured.err


def test_provider_error_after_completed_tools_cannot_pass_probe():
    output = (
        events()
        + "\n"
        + json.dumps({"type": "error", "error": {"type": "unknown", "message": PRIVATE}})
    )
    result = router.inspect_events(output, "implement", 1)
    assert result["passed"] is False
    assert result["code"] == "provider_error"
    assert result["read_ok"] and result["skill_ok"]
    assert result["score"] == 0
    assert PRIVATE not in json.dumps(result)


@pytest.mark.parametrize(
    "extra,code",
    [
        (PRIVATE, "invalid_events"),
        (
            json.dumps(
                {
                    "type": "tool_use",
                    "part": {"id": "pending", "tool": "read", "state": {"status": "running"}},
                }
            ),
            "incomplete_probe",
        ),
        (
            json.dumps(
                {
                    "type": "tool_use",
                    "part": {
                        "id": "failed",
                        "tool": "read",
                        "state": {"status": "error", "error": PRIVATE},
                    },
                }
            ),
            "incomplete_probe",
        ),
        (json.dumps({"type": "step_finish", "part": {"reason": "length"}}), "incomplete_probe"),
    ],
)
def test_partial_or_invalid_probe_never_passes_after_an_earlier_marker(extra, code):
    result = router.inspect_events(events() + "\n" + extra, "plan", 1)
    assert result["passed"] is False
    assert result["code"] == code
    assert PRIVATE not in json.dumps(result)


def test_main_failed_provider_probe_preserves_safe_discovery_and_probe_counts(
    tmp_path, monkeypatch, capsys
):
    report, summary, output = configure_main(tmp_path, monkeypatch)

    def fake_run(args, **kwargs):
        if args[1] == "models":
            return SimpleNamespace(
                returncode=0, stdout=router.APPROVED_FREE_MODELS[1] + "\n", stderr=""
            )
        return SimpleNamespace(
            returncode=0,
            stdout=events() + "\n" + json.dumps({"type": "error", "error": {"message": PRIVATE}}),
            stderr=PRIVATE,
        )

    monkeypatch.setattr(router.subprocess, "run", fake_run)
    assert router.main() == 1
    data = json.loads(report.read_text())
    assert data["failure_code"] == "probe_failed"
    assert data["available"] == [router.APPROVED_FREE_MODELS[1]]
    assert data["discovery"]["approved_count"] == 1
    assert data["probes"][0]["code"] == "provider_error"
    assert data["probes"][0]["stderr_bytes"] == len(PRIVATE)
    assert not output.exists()
    captured = capsys.readouterr()
    assert PRIVATE not in report.read_text() + summary.read_text() + captured.out + captured.err
    assert "provider_error" in captured.out


def test_main_success_report_is_compatible_and_has_discovery_diagnostics(tmp_path, monkeypatch):
    report, summary, output = configure_main(tmp_path, monkeypatch)

    def fake_run(args, **kwargs):
        return SimpleNamespace(
            returncode=0,
            stdout=(
                router.APPROVED_FREE_MODELS[1] + "\n"
                if args[1] == "models"
                else events(task="implement")
            ),
            stderr="",
        )

    monkeypatch.setattr(router.subprocess, "run", fake_run)
    assert router.main() == 0
    data = json.loads(report.read_text())
    assert data["schema_version"] == 1
    assert data["status"] == "success"
    assert data["failure_code"] is None
    assert data["task"] == "implement"
    assert data["selected"] == router.APPROVED_FREE_MODELS[1]
    assert data["probes"][0]["passed"] is True
    assert data["discovery"]["approved_count"] == 1
    assert output.read_text() == "model=" + router.APPROVED_FREE_MODELS[1] + "\n"
