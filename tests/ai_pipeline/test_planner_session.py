"""Research survives cancellation; wrong/missing context is never silently recreated."""

import json
import os
import signal
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from .helpers import module

runner = module("automation/planner_runner")
session = runner.planner_session
FIRST = runner.APPROVED_FREE_MODELS[0]
VALID = {
    "kind": "plan",
    "markdown": "A researched plan with concrete tests.",
    "scope": {"files": ["README.md"], "create": [], "required": []},
}


def test_session_environment_pins_real_directory_and_drops_credentials(tmp_path, monkeypatch):
    monkeypatch.setenv("PWD", "/another/checkout")
    monkeypatch.setenv("GITHUB_TOKEN", "private-token")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "private-key")
    env = session.environment(tmp_path)
    assert env["PWD"] == str(Path.cwd().resolve())
    assert env["XDG_DATA_HOME"] == str(tmp_path.resolve())
    assert "GITHUB_TOKEN" not in env and "ANTHROPIC_API_KEY" not in env


def test_binding_detects_request_and_evidence_changes(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        session.subprocess, "run", lambda *a, **k: SimpleNamespace(stdout=b"sha/diff")
    )
    (tmp_path / "issue-prompt.txt").write_text("original task")
    (tmp_path / "issue-decision.json").write_text("{}")
    evidence = tmp_path / ".planner-evidence"
    evidence.mkdir()
    source = evidence / "source.txt"
    source.write_text("first revision")
    original = session.binding(tmp_path)
    source.write_text("changed revision")
    assert session.binding(tmp_path) != original
    source.write_text("first revision")
    (tmp_path / "issue-prompt.txt").write_text("changed task")
    assert session.binding(tmp_path) != original


@pytest.mark.parametrize(
    "change",
    [
        {"id": "ses_other"},
        {"parentID": "ses_parent"},
        {"agent": "build"},
        {"permissions": [{"action": "*", "effect": "allow"}]},
        {"model": {"providerID": "unapproved", "id": "other"}},
        {"location": {"directory": "/different/checkout"}},
    ],
)
def test_verify_rejects_foreign_or_modified_session(tmp_path, monkeypatch, change):
    provider, name = FIRST.split("/", 1)
    info = {
        "id": "ses_test",
        "agent": "issue-planner",
        "model": {"providerID": provider, "id": name},
        "location": {"directory": str(Path.cwd())},
        **change,
    }

    class Process:
        returncode = 0

        def __init__(self, args, **kwargs):
            assert args[-1] == "/api/session/ses_test"
            kwargs["stdout"].write(json.dumps({"data": info}).encode())

        def wait(self, timeout):
            return 0

    monkeypatch.setattr(session.subprocess, "Popen", Process)
    with pytest.raises(ValueError, match="resume_unavailable"):
        session.verify("ses_test", tmp_path, FIRST, 1)


def test_stop_delivers_term_to_cli_before_killing_tree(monkeypatch):
    calls = []
    monkeypatch.setattr(signal, "SIGKILL", 9, raising=False)

    class Process:
        pid = 123

        def send_signal(self, value):
            calls.append(("signal", value))

        def wait(self, timeout):
            calls.append(("wait", timeout))
            if timeout == 8:
                raise subprocess.TimeoutExpired("private-cli", timeout)

    monkeypatch.setattr(
        session.os, "killpg", lambda *args: calls.append(("killpg", args)), raising=False
    )
    assert session.stop(Process(), 8) is False
    assert calls == [
        ("signal", signal.SIGTERM),
        ("wait", 8),
        ("killpg", (123, signal.SIGKILL)),
        ("wait", 5),
    ]


def test_timeout_observations_explain_work_and_provider_wait_without_content():
    events = [
        {
            "type": "tool_use",
            "sessionID": "ses_test",
            "part": {
                "tool": "read",
                "state": {
                    "status": "completed",
                    "input": {"path": "private-source"},
                    "output": "private-output",
                },
            },
        },
        {
            "type": "step_finish",
            "sessionID": "ses_test",
            "part": {"tokens": {"input": 12, "output": 3}},
        },
        {
            "type": "retry",
            "sessionID": "ses_test",
            "timestamp": 1000,
            "nextRetryAt": 31000,
            "error": {"message": "private-provider-message"},
        },
    ]
    stats = session.observations("\n".join(map(json.dumps, events)), "ses_test")
    assert stats["completed_reads"] == stats["completed_steps"] == stats["provider_retries"] == 1
    assert stats["retry_wait_seconds"] == 30
    assert stats["input_tokens"] == 12 and stats["output_tokens"] == 3
    assert "private" not in json.dumps(stats)
    assert session.observations(json.dumps(events[0]), "ses_other")["session_mismatch"] is True


def test_evidence_coverage_counts_only_completed_actual_reads(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    target = str((tmp_path / "source.txt").resolve())

    def read(status):
        return json.dumps(
            {
                "type": "tool_use",
                "part": {
                    "tool": "read",
                    "state": {"status": status, "input": {"filePath": "source.txt"}},
                },
            }
        )

    assert session.evidence_reads(read("running"), {target}) == set()
    assert session.evidence_reads(read("completed") + "\n" + read("completed"), {target}) == {
        target
    }


@pytest.mark.skipif(os.name == "nt", reason="POSIX signal/process-group integration")
def test_real_cli_cancellation_resumes_persisted_history_and_validates_plan(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "refresh_alternate", lambda *args: None)
    (tmp_path / "issue-prompt.txt").write_text("Research the synthetic source completely")
    (tmp_path / "issue-decision.json").write_text(
        json.dumps(
            {"operation": "plan", "version": 1, "digest": "a" * 64, "issue": {"number": 137}}
        )
    )
    cli = tmp_path / "bin"
    cli.mkdir()
    executable = cli / "opencode"
    executable.write_text(f"""#!{sys.executable}
import json, os, signal, sys, time
from pathlib import Path
state = Path(os.environ['XDG_DATA_HOME'])
state.mkdir(exist_ok=True)
sid = sys.argv[-1].split('/')[-1] if sys.argv[1] == 'api' else sys.argv[sys.argv.index('--session') + 1]
record = state / 'history.json'
if sys.argv[1] == 'api':
    saved = json.loads(record.read_text())
    assert saved['interrupted']
    print(json.dumps({{'data': {{'id': sid, 'agent': 'issue-planner', 'model': {{'providerID': {FIRST.split('/')[0]!r}, 'id': {FIRST.split('/')[1]!r}}}, 'location': {{'directory': os.getcwd()}}}}}}))
    sys.exit(0)
if not record.exists():
    def stop(*args):
        record.write_text(json.dumps({{'session': sid, 'interrupted': True, 'research': 'retained'}}))
        sys.exit(0)
    signal.signal(signal.SIGTERM, stop)
    print(json.dumps({{'type': 'tool_use', 'sessionID': sid, 'part': {{'tool': 'read', 'state': {{'status': 'completed'}}}}}}), flush=True)
    time.sleep(30)
else:
    saved = json.loads(record.read_text())
    assert saved['session'] == sid and saved['research'] == 'retained'
    print(json.dumps({{'type': 'text', 'sessionID': sid, 'part': {{'text': json.dumps({VALID!r})}}}}))
""")
    executable.chmod(0o755)
    monkeypatch.setenv("PATH", str(cli) + os.pathsep + os.environ["PATH"])
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    report = runner.run_plan(
        tmp_path,
        FIRST,
        {"task": "plan", "selected": FIRST, "probes": [{"model": FIRST, "passed": True}]},
        checkpoint_seconds=0.3,
    )
    assert report["status"] == "success"
    assert report["attempts"][0]["completed_reads"] == 1
    assert report["attempts"][0]["graceful_stop"] is True
    assert report["attempts"][1]["resumed"] is True
    assert (tmp_path / "issue-result.json").exists()


def test_private_replay_has_no_publisher_and_exports_only_numeric_diagnostics():
    import yaml

    root = Path(__file__).resolve().parents[2]
    workflow = yaml.safe_load((root / ".github/workflows/ai-planner-live-tests.yml").read_text())
    assert set(workflow["permissions"].values()) == {"read"}
    assert "github.repository_owner" in workflow["jobs"]["replay"]["if"]
    for step in workflow["jobs"]["replay"]["steps"]:
        if step.get("uses", "").startswith("actions/upload-artifact"):
            assert set(step["with"]["path"].splitlines()) == {
                "${{ runner.temp }}/planner-diagnostics.json",
                "${{ runner.temp }}/model-router.json",
            }
    script = (root / "scripts/automation/planner_diagnostic.py").read_text()
    assert "checkpoint_seconds=90" in script
    assert "issue_bot.prepare_research_prompt" in script
