"""Unit tests for the approved-free-model OpenCode router."""

import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "opencode_model_router.py"
SPEC = importlib.util.spec_from_file_location("opencode_model_router", SCRIPT)
assert SPEC and SPEC.loader
router = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(router)


def events(text="ROUTER_OK\nknx_to_openhab supports legacy and yaml."):
    """Include genuinely completed skill/read tool calls."""
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
                "opencode/glm-5.3-flash-free",
                "opencode/deepseek-v4.1-flash-free",
                "opencode/some-unknown-free",
                "opencode/glm-5.3-flash",
                "openai/gpt-6",
                "not-opencode/foo-free",
                "opencode/glm-5.3-flash-free --some flag",
            ]
        )
    )
    assert "opencode/glm-5.3-flash-free" in found
    assert "opencode/deepseek-v4.1-flash-free" in found
    assert "opencode/glm-5.3-flash" not in found
    assert "openai/gpt-6" not in found
    assert "opencode/glm-5.3-flash-free --some flag" not in found
    assert "opencode/some-unknown-free" in found
    assert set(router.APPROVED_FREE_MODELS) == {
        "opencode/glm-5.3-flash-free",
        "opencode/deepseek-v4.1-flash-free",
    }


def test_probe_requires_completed_read_and_skill():
    result = router.inspect_events(events(), "plan", 12)
    assert result["passed"] is True
    assert result["read_ok"] is True
    assert result["skill_ok"] is True
    assert result["factual"] is True
    assert result["score"] > 0


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
        router.choose_model(
            [{"model": "openai/gpt-6", "passed": True, "score": 999}]
        )


def test_discovery_intersects_with_allowlist(monkeypatch):
    def fake_run(args, **kwargs):
        assert args == ["opencode", "models", "opencode", "--refresh"]
        assert kwargs["timeout"] == router.DISCOVERY_TIMEOUT
        return SimpleNamespace(
            returncode=0,
            stdout=(
                "opencode/glm-5.3-flash-free\n"
                "opencode/fake-free\n"
                "openai/gpt-6\n"
            ),
        )

    monkeypatch.setattr(router.subprocess, "run", fake_run)
    assert router.discover_models() == {"opencode/glm-5.3-flash-free"}


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
        ["opencode", "models", "opencode", "--refresh"],
        ["opencode", "models"],
    ]


def test_probes_are_bounded_and_read_only(monkeypatch):
    def fake_run(args, **kwargs):
        assert "--agent" in args
        assert args[args.index("--agent") + 1] == "ci-smoke"
        assert args[args.index("--model") + 1] == router.APPROVED_FREE_MODELS[0]
        assert kwargs["timeout"] == router.PROBE_TIMEOUT
        assert "GITHUB_TOKEN" not in kwargs["env"]
        return SimpleNamespace(returncode=0, stdout=events())

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


def test_main_exports_only_selected_allowlisted_model(tmp_path, monkeypatch):
    monkeypatch.setattr(router, "discover_models", lambda: set(router.APPROVED_FREE_MODELS))
    monkeypatch.setattr(
        router,
        "probe_model",
        lambda model, task: {
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


def test_main_refuses_all_failed_models(tmp_path, monkeypatch):
    monkeypatch.setattr(router, "discover_models", lambda: set(router.APPROVED_FREE_MODELS))
    monkeypatch.setattr(
        router,
        "probe_model",
        lambda model, task: {"model": model, "passed": False, "score": 0},
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
