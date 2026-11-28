"""Permissions and ordering of formatter/reporting jobs stay explicit."""

import os
import shlex
import subprocess
import sys
from importlib.metadata import version
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


@pytest.mark.parametrize(
    ("workflow", "job_name"),
    [("ai-issue-implement.yml", "implement"), ("opencode-ci-self-repair.yml", "repair")],
)
def test_isolated_formatter_runtime_is_ready_before_any_model_work(workflow, job_name, tmp_path):
    definition = yaml.safe_load((ROOT / ".github/workflows" / workflow).read_text())
    steps = definition["jobs"][job_name]["steps"]
    runtimes = [
        (index, step)
        for index, step in enumerate(steps)
        if step.get("uses", "").startswith("actions/setup-python@")
    ]
    assert len(runtimes) == 1, "The model job needs an explicit shared Python runtime"
    runtime_index, runtime = runtimes[0]
    assert runtime["with"]["python-version"] == "3.12"

    python_commands = []
    for index, step in enumerate(steps):
        for line in step.get("run", "").replace("\\\n", " ").splitlines():
            command = shlex.split(line, comments=True)
            if command and Path(command[0]).name.startswith("python"):
                python_commands.append((index, command))
    # Resolve tools through the runtime installed above, not the runner's system Python.
    assert all(command[0] == "python" for _, command in python_commands)
    probes = {
        command[3]: (index, command)
        for index, command in python_commands
        if command[:3] == ["python", "-I", "-m"]
        and len(command) > 3
        and command[3] in {"isort", "black"}
    }
    assert probes.keys() == {"isort", "black"}, "Exercise both modules with isolated imports"
    bootstrap_index = probes["isort"][0]
    assert probes["black"][0] == bootstrap_index
    bootstrap = steps[bootstrap_index]
    assert bootstrap["working-directory"] == "trusted"
    assert not bootstrap.get("continue-on-error", False)
    assert bootstrap.get("if", "success()") == "success()"
    assert runtime_index < bootstrap_index == min(index for index, _ in python_commands)
    candidate_checkout = next(
        index for index, step in enumerate(steps) if step.get("with", {}).get("path") == "candidate"
    )
    assert bootstrap_index < candidate_checkout
    install = [
        (index, command)
        for index, command in python_commands
        if "pip" in command and "install" in command
    ]
    assert len(install) == 1, "Do not defer installation until after costly generation"
    install_index, install_command = install[0]
    assert install_index == bootstrap_index
    assert install_command[:5] == ["python", "-I", "-m", "pip", "--isolated"]
    assert "--no-user" in install_command and "--user" not in install_command
    pinned = {
        line.strip()
        for line in (ROOT / "requirements-dev.txt").read_text().splitlines()
        if line.startswith(("black==", "isort=="))
    }
    assert len(pinned) == 2 and pinned.issubset(install_command)

    # Run the real preflight commands from the workflow, without a network install.
    # A successful ordinary import is insufficient: -I must ignore injected modules.
    poison = tmp_path / "untrusted-imports"
    poison.mkdir()
    for module in probes:
        (poison / f"{module}.py").write_text("raise RuntimeError('untrusted formatter import')\n")
    env = {**os.environ, "PYTHONPATH": str(poison), "PYTHONUSERBASE": str(tmp_path / "user")}
    for module, (_, command) in probes.items():
        assert command[4:] == ["--version-number" if module == "isort" else "--version"]
        result = subprocess.run(
            [sys.executable, *command[1:]],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, result.stderr
        assert version(module) in result.stdout


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
    # Two catalogs and five bounded probes; repair also fetches a CI log.
    # Leave at least four more minutes for setup, validation and uploads.
    preparation_seconds = 415 + (40 if mode == "repair" else 0)
    assert job["timeout-minutes"] * 60 >= budget_seconds + preparation_seconds + 240
    steps = job["steps"]
    generation = next(step for step in steps if step.get("id") == "generation")
    assert generation["run"] == (
        f"python -I ../trusted/scripts/automation/generation_runner.py --mode {mode}"
    )
    assert generation["working-directory"] == "candidate"
    assert generation["timeout-minutes"] * 60 > budget_seconds
    assert generation["env"] == {
        "CI": "true",
        "MODEL": "${{ steps.model.outputs.model }}",
        "OPENROUTER_API_KEY": "${{ secrets.OPENROUTER_API_KEY }}",
    }
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
    assert "--task " + job_name in selection["run"]
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
