"""Permissions and ordering of formatter/reporting jobs stay explicit."""

from pathlib import Path

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
