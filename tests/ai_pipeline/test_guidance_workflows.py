"""Permissions and ordering of formatter/reporting jobs stay explicit."""

from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]


def test_notifications_never_gain_source_write_permissions_or_execute_candidate():
    for name in ["ai-issue-implement.yml", "opencode-ci-self-repair.yml", "ai-workflow-status.yml"]:
        definition = yaml.safe_load((ROOT / ".github/workflows" / name).read_text())
        for job_id, job in definition["jobs"].items():
            if job_id not in {"announce", "notify", "notify-failure", "report"}:
                continue
            permissions = job.get("permissions", definition.get("permissions", {}))
            assert permissions["issues"] == "write"
            assert permissions["contents"] == "read"
            assert permissions.get("pull-requests") == "read"
            for step in job["steps"]:
                assert "run" not in step
                if step.get("uses", "").startswith("actions/checkout"):
                    assert step["with"]["ref"] == "${{ github.event.repository.default_branch }}"
                    assert step["with"]["persist-credentials"] is False


def test_formatting_happens_after_agent_restore_and_before_final_collection():
    for name, command in [
        ("ai-issue-implement.yml", "issue_implement"),
        ("opencode-ci-self-repair.yml", "ci_repair"),
    ]:
        source = (ROOT / ".github/workflows" / name).read_text()
        assert source.index("git restore --source=HEAD") < source.index(f"{command}.py format")
        assert source.index(f"{command}.py format") < source.index(f"{command}.py collect")


def test_planning_context_read_permissions_and_trusted_source():
    definition = yaml.safe_load((ROOT / ".github/workflows/opencode-issue-planner.yml").read_text())
    assert definition["permissions"]["pull-requests"] == "read"
    steps = definition["jobs"]["plan"]["steps"]
    source = next(s for s in steps if s.get("name") == "Fetch bot comments")["with"]["script"]
    assert "/trusted/scripts/automation/planning.cjs" in source


@pytest.mark.parametrize(
    ("workflow", "job_name", "mode", "budget_seconds"),
    [
        ("ai-issue-implement.yml", "implement", "implement", 1800),
        ("opencode-ci-self-repair.yml", "repair", "repair", 1000),
    ],
)
def test_generation_diagnostics_survive_failure_without_publishing_partial_code(
    workflow, job_name, mode, budget_seconds
):
    definition = yaml.safe_load((ROOT / ".github/workflows" / workflow).read_text())
    job = definition["jobs"][job_name]
    assert all(value == "read" for value in job["permissions"].values())
    # Router discovery/probes can take 320 seconds; repair also fetches a CI log.
    # Leave at least four more minutes for setup, validation and uploads.
    preparation_seconds = 320 + (40 if mode == "repair" else 0)
    assert job["timeout-minutes"] * 60 >= budget_seconds + preparation_seconds + 240
    steps = job["steps"]
    generation = next(step for step in steps if step.get("id") == "generation")
    assert generation["run"] == (
        f"python -I ../trusted/scripts/automation/generation_runner.py --mode {mode}"
    )
    assert generation["working-directory"] == "candidate"
    assert generation["timeout-minutes"] * 60 > budget_seconds
    assert generation["env"] == {"CI": "true", "MODEL": "${{ steps.model.outputs.model }}"}
    assert not generation.get("continue-on-error", False)

    diagnostics = next(
        step
        for step in steps
        if step.get("with", {}).get("path") == "${{ runner.temp }}/generation-diagnostics.json"
    )
    assert diagnostics["uses"].startswith("actions/upload-artifact@")
    assert "always()" in diagnostics["if"]
    assert "steps.generation.outcome == 'failure'" in diagnostics["if"]
    assert "steps.generation.outcome == 'success'" in diagnostics["if"]
    assert "${{ github.run_attempt }}" in diagnostics["with"]["name"]
    assert diagnostics["with"]["if-no-files-found"] == "error"
    assert steps.index(generation) < steps.index(diagnostics)

    final_checks = next(
        step for step in steps if "git restore --source=HEAD" in step.get("run", "")
    )
    assert steps.index(diagnostics) < steps.index(final_checks)
    assert not final_checks.get("continue-on-error", False)
    assert final_checks.get("if", "success()") == "success()"
    assert ".py format" in final_checks["run"]
    assert ".py collect" in final_checks["run"]
    candidate = next(
        step
        for step in steps
        if step.get("with", {}).get("path") == "${{ runner.temp }}/task-artifact.json"
    )
    assert steps.index(final_checks) < steps.index(candidate)
    assert candidate.get("if", "success()") == "success()"
    publisher = definition["jobs"]["publish"]
    assert job_name in publisher["needs"]
    assert publisher.get("if", "success()") == "success()"


@pytest.mark.parametrize(
    ("workflow", "job_name", "report_path", "generation_command"),
    [
        ("ai-issue-implement.yml", "implement", "model.json", "generation_runner.py"),
        ("opencode-ci-self-repair.yml", "repair", "model.json", "generation_runner.py"),
        ("opencode-issue-planner.yml", "plan", "model-router.json", "planner_runner.py"),
    ],
)
def test_router_failure_has_its_own_diagnostics_before_generation(
    workflow, job_name, report_path, generation_command
):
    definition = yaml.safe_load((ROOT / ".github/workflows" / workflow).read_text())
    steps = definition["jobs"][job_name]["steps"]
    selection = next(step for step in steps if step.get("id") == "model")
    diagnostics = next(
        step
        for step in steps
        if step.get("name") == "Preserve content-free model selection diagnostics"
    )
    assert diagnostics["uses"].startswith("actions/upload-artifact@")
    assert diagnostics["with"]["path"] == "${{ runner.temp }}/" + report_path
    assert "always()" in diagnostics["if"]
    for outcome in ("success", "failure", "cancelled"):
        assert f"steps.model.outcome == '{outcome}'" in diagnostics["if"]
    assert "steps.generation" not in diagnostics["if"]
    assert "${{ github.run_id }}" in diagnostics["with"]["name"]
    assert "${{ github.run_attempt }}" in diagnostics["with"]["name"]
    assert diagnostics["with"]["if-no-files-found"] == "error"
    generation = next(step for step in steps if generation_command in step.get("run", ""))
    assert steps.index(selection) < steps.index(diagnostics) < steps.index(generation)
    assert not selection.get("continue-on-error", False)
    assert not generation.get("continue-on-error", False)
    assert "always()" not in generation.get("if", "")
