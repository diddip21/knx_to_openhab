"""Planner failures are simulated locally; these tests never contact a model provider."""

import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

MODULE = Path(__file__).resolve().parents[1] / "scripts/automation/planner_runner.py"
SPEC = importlib.util.spec_from_file_location("planner_runner", MODULE)
assert SPEC and SPEC.loader
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)
response_module = sys.modules["automation.model_response"]

FIRST, SECOND = runner.APPROVED_FREE_MODELS
SCOPE = {"files": ["README.md"], "create": [], "required": []}
VALID = {"kind": "plan", "markdown": "## Plan\n\nUpdate the public documentation.", "scope": SCOPE}


def event(response=VALID):
    return json.dumps({"type": "text", "part": {"text": json.dumps(response)}}) + "\n"


def router_report(second_passed=True):
    return {
        "selected": FIRST,
        "probes": [{"model": FIRST, "passed": True}, {"model": SECOND, "passed": second_passed}],
    }


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    (tmp_path / "issue-prompt.txt").write_text("Private issue context must not enter diagnostics")
    (tmp_path / "issue-decision.json").write_text(
        json.dumps(
            {
                "operation": "plan",
                "version": 4,
                "digest": "a" * 64,
                "issue": {"number": 137},
                "planning_snapshot": {"previous_plan_id": 10},
            }
        )
    )
    return tmp_path


def fake_attempts(monkeypatch, outputs, exit_code=0):
    calls = []

    def execute(model, prompt, timeout):
        calls.append((model, prompt, timeout))
        return outputs[len(calls) - 1], {
            "code": None,
            "exit_code": exit_code,
            "elapsed_seconds": 0.01,
            "stdout_bytes": len(outputs[len(calls) - 1]),
            "stderr_bytes": 42,
        }

    monkeypatch.setattr(runner, "execute", execute)
    return calls


def test_format_retry_then_verified_alternate_publish_one_valid_plan(runtime, monkeypatch):
    bad = json.dumps({"type": "text", "part": {"text": "Not JSON"}})
    calls = fake_attempts(monkeypatch, [bad, bad, event()])

    report = runner.run_plan(runtime, FIRST, router_report())

    assert [c[0] for c in calls] == [FIRST, FIRST, SECOND]
    assert "invalid_json" in calls[1][1]
    assert "16000" in calls[1][1]
    assert [a["phase"] for a in report["attempts"]] == ["initial", "format_retry", "fallback"]
    result = json.loads((runtime / "issue-result.json").read_text())
    assert result["version"] == 4
    assert '"scope"' in result["comment"]
    assert "/ai approve v4" in result["comment"]


def test_provider_error_with_zero_exit_skips_format_retry_and_retains_no_content(
    runtime, monkeypatch
):
    secret = "fake-provider-secret-do-not-retain"
    failed = event() + json.dumps({"type": "error", "error": {"message": secret}})
    calls = fake_attempts(monkeypatch, [failed, event()])

    report = runner.run_plan(runtime, FIRST, router_report())

    assert [c[0] for c in calls] == [FIRST, SECOND]
    assert report["attempts"][0]["code"] == "provider_error"
    saved = (runtime / "planner-diagnostics.json").read_text()
    assert secret not in saved
    assert "Private issue context" not in saved
    assert VALID["markdown"] not in saved
    assert "README.md" not in saved
    assert len(saved) < 5000


def test_provider_diagnostics_keep_only_a_numeric_http_status():
    output = json.dumps(
        {"type": "error", "error": {"data": {"statusCode": 429, "message": "private-data"}}}
    )

    with pytest.raises(response_module.ModelResponseError) as caught:
        response_module.inspect_events(output)

    assert caught.value.diagnostics["provider_http_status"] == 429
    assert "private-data" not in str(caught.value)


def test_invalid_scope_is_never_published_even_after_all_attempts(runtime, monkeypatch):
    invalid = {**VALID, "scope": {"files": [".github/workflows/ci.yml"]}}
    calls = fake_attempts(monkeypatch, [event(invalid)] * 3)
    (runtime / "issue-result.json").write_text('{"stale":true}')

    with pytest.raises(ValueError, match="invalid_scope"):
        runner.run_plan(runtime, FIRST, router_report())

    assert len(calls) == 3
    assert not (runtime / "issue-result.json").exists()
    report = json.loads((runtime / "planner-diagnostics.json").read_text())
    assert report["status"] == "failure"
    assert report["failure_code"] == "invalid_scope"


def test_cli_failure_is_not_classified_as_a_format_problem(runtime, monkeypatch):
    calls = fake_attempts(monkeypatch, ["", ""], exit_code=2)

    with pytest.raises(ValueError, match="cli_error"):
        runner.run_plan(runtime, FIRST, router_report())

    assert [c[0] for c in calls] == [FIRST, SECOND]


def test_failed_probe_cannot_be_used_as_fallback(runtime, monkeypatch):
    bad = json.dumps({"type": "text", "part": {"text": "Not JSON"}})
    calls = fake_attempts(monkeypatch, [bad, bad])

    with pytest.raises(ValueError, match="invalid_json"):
        runner.run_plan(runtime, FIRST, router_report(second_passed=False))

    assert [c[0] for c in calls] == [FIRST, FIRST]


def test_unapproved_model_does_not_run_or_appear_in_diagnostics(runtime, monkeypatch):
    calls = fake_attempts(monkeypatch, [])
    model = "unapproved/secret-example"

    with pytest.raises(ValueError, match="invalid_router_report"):
        runner.run_plan(runtime, model, {"selected": model, "probes": []})

    assert not calls
    assert model not in (runtime / "planner-diagnostics.json").read_text()


def test_total_budget_stops_retries(runtime, monkeypatch):
    times = iter([0, 0, 661, 661])
    monkeypatch.setattr(runner.time, "monotonic", lambda: next(times))
    bad = json.dumps({"type": "text", "part": {"text": "Not JSON"}})
    calls = fake_attempts(monkeypatch, [bad])

    with pytest.raises(ValueError, match="budget_exhausted"):
        runner.run_plan(runtime, FIRST, router_report())

    assert len(calls) == 1


@pytest.mark.parametrize(
    ("response", "code"),
    [
        ({"kind": "plan", "markdown": "x" * 20}, "missing_scope"),
        ({**VALID, "markdown": "x" * 16001}, "markdown_too_long"),
        ({**VALID, "kind": "unknown"}, "invalid_schema"),
    ],
)
def test_real_response_schema_and_scope_are_checked(response, code):
    with pytest.raises(ValueError, match=code):
        response_module.parse_response(json.dumps(response))


def test_questions_do_not_require_a_file_scope():
    result = response_module.parse_response(
        json.dumps({"kind": "questions", "markdown": "Which output format should be preserved?"})
    )
    assert result["kind"] == "questions"


@pytest.mark.parametrize("value", [None, False, 42, "JSON scalar", []])
def test_valid_json_with_the_wrong_type_is_a_schema_error(value):
    with pytest.raises(ValueError, match="invalid_schema"):
        response_module.parse_response(json.dumps(value))


def test_duplicate_keys_and_malformed_root_do_not_hide_a_valid_nested_plan():
    for response in [
        '{"kind":"plan","kind":"questions","markdown":"A valid length response"}',
        '{"broken":!,"nested":' + json.dumps(VALID) + "}",
    ]:
        with pytest.raises(ValueError, match="invalid_json"):
            response_module.parse_response(response)


def write_fake_cli(directory, source):
    executable = directory / "opencode"
    executable.write_text(f"#!{sys.executable}\n" + source)
    executable.chmod(0o755)


def test_simulated_cli_retries_and_isolates_credentials(runtime, monkeypatch):
    cli = runtime / "bin"
    cli.mkdir()
    state = runtime / "calls.json"
    payloads = [
        {"type": "text", "part": {"text": "Not JSON"}},
        {"type": "text", "part": {"text": json.dumps(VALID)}},
    ]
    write_fake_cli(
        cli,
        f"""import json, os, sys
from pathlib import Path
assert 'GITHUB_TOKEN' not in os.environ
state = Path({str(state)!r})
calls = json.loads(state.read_text()) if state.exists() else []
calls.append(sys.argv[sys.argv.index('--model') + 1])
state.write_text(json.dumps(calls))
payloads = {payloads!r}
print(json.dumps(payloads[len(calls) - 1]))
print('fake-secret-on-stderr', file=sys.stderr)
""",
    )
    monkeypatch.setenv("PATH", str(cli) + os.pathsep + os.environ["PATH"])
    monkeypatch.setenv("GITHUB_TOKEN", "fake-secret-in-environment")

    report = runner.run_plan(runtime, FIRST, router_report())

    assert report["status"] == "success"
    assert json.loads(state.read_text()) == [FIRST, FIRST]
    assert "fake-secret" not in (runtime / "planner-diagnostics.json").read_text()


def test_real_cli_timeout_kills_attempt_without_waiting_for_its_sleep(runtime, monkeypatch):
    cli = runtime / "bin"
    cli.mkdir()
    write_fake_cli(cli, "import time\ntime.sleep(30)\n")
    monkeypatch.setenv("PATH", str(cli) + os.pathsep + os.environ["PATH"])

    _, metrics = runner.execute(FIRST, "read-only probe", timeout=0.1)

    assert metrics["code"] == "timeout"
    assert metrics["elapsed_seconds"] < 5


def test_real_cli_output_is_bounded(runtime, monkeypatch):
    cli = runtime / "bin"
    cli.mkdir()
    write_fake_cli(cli, "import sys\nsys.stdout.write('x' * 2000000)\n")
    monkeypatch.setenv("PATH", str(cli) + os.pathsep + os.environ["PATH"])

    output, metrics = runner.execute(FIRST, "read-only probe", timeout=5)

    assert metrics["code"] == "output_limit"
    assert len(output) <= runner.MAX_EVENT_BYTES


def test_failure_artifacts_include_only_explicit_content_free_diagnostic_files():
    workflow = (MODULE.parents[2] / ".github/workflows/opencode-issue-planner.yml").read_text(
        encoding="utf-8"
    )
    upload = workflow.split("- name: Retain content-free planner diagnostics", 1)[1]
    paths = upload.split("path: |", 1)[1].split("if-no-files-found:", 1)[0]

    assert {line.strip() for line in paths.splitlines() if line.strip()} == {
        "${{ runner.temp }}/planner-diagnostics.json",
        "${{ runner.temp }}/model-router.json",
    }
