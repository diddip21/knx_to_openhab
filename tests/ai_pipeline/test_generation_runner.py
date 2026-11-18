"""Real short CLI processes and isolated Git repos; no provider or GitHub calls."""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
from automation import artifacts
from automation import generation_runner as runner

from .helpers import ROOT, context, git, init_repo

FIRST, SECOND = runner.APPROVED_FREE_MODELS
PRIVATE = "never-publish-private-prompt-source-provider-value"


def setup_runtime(tmp_path, monkeypatch, *, scope=None, mode="implement", second=True):
    root = init_repo(tmp_path / "candidate")
    temp = tmp_path / "runtime"
    temp.mkdir()
    approved = context(root, scope=scope)
    approved["mode"] = mode
    if mode == "repair":
        approved["attempt"] = 2
    (temp / "task-context.json").write_text(json.dumps(approved))
    (temp / "task-prompt.txt").write_text(PRIVATE)
    (temp / "model.json").write_text(
        json.dumps(
            {
                "task": "implement",
                "selected": FIRST,
                "probes": [{"model": FIRST, "passed": True}, {"model": SECOND, "passed": second}],
            }
        )
    )
    artifacts.write_agent(
        root, approved, ROOT / ".opencode/agents/ai-task.md", repair=mode == "repair"
    )
    monkeypatch.setenv("RUNNER_TEMP", str(temp))
    monkeypatch.setenv("MODEL", FIRST)
    monkeypatch.setattr(runner, "MODE_LIMITS", {"implement": (3.0, 6.0), "repair": (3.0, 6.0)})
    monkeypatch.setattr(runner, "INTERRUPTED", False)
    return root, temp


def fake_cli(tmp_path, monkeypatch, code):
    directory = tmp_path / "bin"
    directory.mkdir(exist_ok=True)
    calls = tmp_path / "calls.json"
    program = directory / "opencode"
    program.write_text(
        f"#!{sys.executable}\n"
        "import json, os, signal, subprocess, sys, time\nfrom pathlib import Path\n"
        f"PRIVATE = {PRIVATE!r}\n"
        f"calls_path = Path({str(calls)!r})\n"
        "calls = json.loads(calls_path.read_text()) if calls_path.exists() else []\n"
        "model = sys.argv[sys.argv.index('--model') + 1]\n"
        "calls.append(model)\ncalls_path.write_text(json.dumps(calls))\n"
        "def emit(value):\n    print(json.dumps(value), flush=True)\n"
        "def valid():\n"
        "    emit({'type': 'text', 'part': {'text': PRIVATE}})\n"
        "    emit({'type': 'step_finish', 'part': {'reason': 'stop'}})\n"
        "def changed():\n"
        "    Path('feature.py').write_text('value = 1\\n')\n"
        "    Path('tests/test_feature.py').write_text('from feature import value\\n\\ndef test_value():\\n    assert value == 1\\n')\n"
        + code
        + "\n"
    )
    program.chmod(0o755)
    monkeypatch.setenv("PATH", str(directory) + os.pathsep + os.environ["PATH"])
    return calls


def diagnostics(temp):
    text = (temp / "generation-diagnostics.json").read_text()
    assert PRIVATE not in text
    assert "feature.py" not in text
    assert "task-prompt" not in text
    assert len(text) < 15_000
    return json.loads(text)


def fails(root, temp, code, mode="implement"):
    with pytest.raises(runner.GenerationError, match=f"^{code}$"):
        runner.run_generation(root, temp, mode, FIRST)
    report = diagnostics(temp)
    assert report["status"] == "failure"
    assert report["failure_code"] == code
    return report


def test_success_preserves_dynamic_agent_and_requires_downstream_collect(tmp_path, monkeypatch):
    root, temp = setup_runtime(tmp_path, monkeypatch)
    dynamic = (root / runner.AGENT_PATH).read_bytes()
    fake_cli(tmp_path, monkeypatch, "changed()\nvalid()")
    report = runner.run_generation(root, temp, "implement", FIRST)
    assert report["status"] == "success"
    assert report["attempts"][0]["changed_files"] == 2
    assert report["attempts"][0]["required_files_changed"] == 1
    assert (root / runner.AGENT_PATH).read_bytes() == dynamic
    assert not (temp / "task-artifact.json").exists()
    assert not (temp / "task-events.jsonl").exists()
    assert not (temp / "task-stderr.log").exists()
    diagnostics(temp)
    # Existing trusted artifact validation remains necessary, including agent restore.
    with pytest.raises(ValueError):
        artifacts.collect(json.loads((temp / "task-context.json").read_text()), root, repair=False)
    git(root, "restore", "--", runner.AGENT_PATH)
    artifact = artifacts.collect(
        json.loads((temp / "task-context.json").read_text()), root, repair=False
    )
    assert len(artifact["files"]) == 2


def test_provider_error_even_with_zero_exit_is_redacted(tmp_path, monkeypatch, capsys):
    root, temp = setup_runtime(tmp_path, monkeypatch, second=False)
    fake_cli(
        tmp_path,
        monkeypatch,
        f"print({PRIVATE!r}, file=sys.stderr)\nemit({{'type': 'error', 'error': {{'message': {PRIVATE!r}, 'data': {{'statusCode': 429}}}}}})\n"
        "valid()",
    )
    report = fails(root, temp, "provider_error")
    attempt = report["attempts"][0]
    assert attempt["exit_code"] == 0
    assert attempt["provider_http_status"] == 429
    assert attempt["stderr_bytes"] > 0
    assert PRIVATE not in capsys.readouterr().out


def test_fallback_restores_only_authorized_changes_including_new_files(tmp_path, monkeypatch):
    scope = {
        "files": ["feature.py", "tests/test_feature.py", "docs/new/note.md"],
        "create": ["docs/new/note.md"],
        "required": ["tests/test_feature.py"],
    }
    root, temp = setup_runtime(tmp_path, monkeypatch, scope=scope)
    original_agent = (root / runner.AGENT_PATH).read_bytes()
    calls = fake_cli(
        tmp_path,
        monkeypatch,
        "if len(calls) == 1:\n"
        "    Path('feature.py').write_text('partial = 9\\n')\n"
        "    Path('docs/new').mkdir()\n"
        "    Path('docs/new/note.md').write_text('partial\\n')\n"
        "    emit({'type': 'error', 'error': {'message': 'private failure'}})\n"
        "else:\n"
        "    assert Path('feature.py').read_text() == 'value = 0\\n'\n"
        "    assert not Path('docs/new').exists()\n"
        f"    assert Path({runner.AGENT_PATH!r}).read_bytes() == {original_agent!r}\n"
        "    changed()\n    valid()",
    )
    report = runner.run_generation(root, temp, "implement", FIRST)
    assert json.loads(calls.read_text()) == [FIRST, SECOND]
    assert [a["code"] for a in report["attempts"]] == ["provider_error", "candidate_generated"]
    assert report["attempts"][0]["scoped_rollback"] is True
    assert (root / runner.AGENT_PATH).read_bytes() == original_agent
    assert (
        git(root, "rev-parse", "HEAD")
        == json.loads((temp / "task-context.json").read_text())["base_commit_sha"]
    )
    diagnostics(temp)


def test_timeout_with_partial_output_and_scoped_changes_falls_back(tmp_path, monkeypatch):
    root, temp = setup_runtime(tmp_path, monkeypatch)
    monkeypatch.setattr(runner, "MODE_LIMITS", {"implement": (0.4, 0.9)})
    calls = fake_cli(
        tmp_path,
        monkeypatch,
        "if len(calls) == 1:\n"
        "    Path('feature.py').write_text('partial = 4\\n')\n"
        "    emit({'type': 'tool_use', 'part': {'id': 'a', 'tool': 'read', 'state': {'status': 'running'}}})\n"
        "    time.sleep(3)\n"
        "else:\n"
        "    assert Path('feature.py').read_text() == 'value = 0\\n'\n"
        "    changed()\n    valid()",
    )
    report = runner.run_generation(root, temp, "implement", FIRST)
    assert json.loads(calls.read_text()) == [FIRST, SECOND]
    assert report["attempts"][0]["code"] == "timeout"
    assert report["attempts"][0]["events"]["tool_use"] == 1
    assert report["attempts"][0]["pending_tools"] == 1
    assert report["attempts"][1]["limit_seconds"] <= 0.5


def test_timeout_kills_child_process_before_it_can_write(tmp_path, monkeypatch):
    root, temp = setup_runtime(tmp_path, monkeypatch, second=False)
    monkeypatch.setattr(runner, "MODE_LIMITS", {"implement": (0.4, 0.9)})
    marker = tmp_path / "child-alive"
    child = f"import time; from pathlib import Path; time.sleep(0.8); Path({str(marker)!r}).write_text('bad')"
    fake_cli(
        tmp_path, monkeypatch, f"subprocess.Popen([sys.executable, '-c', {child!r}])\ntime.sleep(3)"
    )
    report = fails(root, temp, "timeout")
    assert report["attempts"][0]["elapsed_seconds"] < 1.2
    time.sleep(0.85)
    assert not marker.exists()


def test_successful_parent_cannot_leave_a_background_writer(tmp_path, monkeypatch):
    root, temp = setup_runtime(tmp_path, monkeypatch)
    child = "import time; from pathlib import Path; time.sleep(0.5); Path('feature.py').write_text('late = 9\\n')"
    fake_cli(
        tmp_path,
        monkeypatch,
        f"changed()\nsubprocess.Popen([sys.executable, '-c', {child!r}])\nvalid()",
    )
    report = runner.run_generation(root, temp, "implement", FIRST)
    assert report["status"] == "success"
    time.sleep(0.55)
    assert (root / "feature.py").read_text() == "value = 1\n"


def test_process_closing_both_pipes_still_has_a_deadline(tmp_path, monkeypatch):
    root, temp = setup_runtime(tmp_path, monkeypatch, second=False)
    monkeypatch.setattr(runner, "MODE_LIMITS", {"implement": (0.4, 0.9)})
    fake_cli(tmp_path, monkeypatch, "os.close(1)\nos.close(2)\ntime.sleep(3)")
    assert fails(root, temp, "timeout")["elapsed_seconds"] < 1.2


@pytest.mark.parametrize("stream", ["stdout", "stderr"])
def test_output_capture_has_live_byte_caps(tmp_path, monkeypatch, stream):
    root, temp = setup_runtime(tmp_path, monkeypatch, second=False)
    monkeypatch.setattr(runner, "MAX_STDOUT_BYTES", 2048)
    monkeypatch.setattr(runner, "MAX_STDERR_BYTES", 2048)
    fake_cli(
        tmp_path,
        monkeypatch,
        f"os.write({1 if stream == 'stdout' else 2}, b'x' * 20_000)\ntime.sleep(3)",
    )
    report = fails(root, temp, "output_limit")
    assert report["attempts"][0][f"{stream}_bytes"] > 2048


@pytest.mark.parametrize(
    "body,code",
    [
        ("print('private invalid JSON')", "invalid_events"),
        ("emit({'type': 'text', 'part': {'text': ''}})", "empty_response"),
        (
            "valid()\nemit({'type': 'step_finish', 'part': {'reason': 'max_steps'}})",
            "output_truncated",
        ),
        (
            "valid()\nemit({'type': 'tool_use', 'part': {'tool': 'edit', 'state': {'status': 'running'}}})",
            "incomplete_tools",
        ),
        (
            "valid()\nemit({'type': 'tool_use', 'part': {'tool': 'read', 'state': {'status': 'error', 'error': 'private'}}})",
            "tool_error",
        ),
        ("sys.exit(7)", "cli_error"),
    ],
)
def test_parser_and_cli_failure_codes_are_fixed(tmp_path, monkeypatch, body, code):
    root, temp = setup_runtime(tmp_path, monkeypatch, second=False)
    fake_cli(tmp_path, monkeypatch, body)
    fails(root, temp, code)


def test_disallowed_tool_stays_policy_failure_after_later_provider_error(tmp_path, monkeypatch):
    root, temp = setup_runtime(tmp_path, monkeypatch)
    calls = fake_cli(
        tmp_path,
        monkeypatch,
        f"emit({{'type': 'tool_use', 'part': {{'tool': {PRIVATE!r}, 'state': {{'status': 'error', 'input': {{'command': {PRIVATE!r}}}}}}}}})\n"
        "emit({'type': 'error', 'error': {'message': 'provider error'}})",
    )
    report = fails(root, temp, "tool_policy")
    assert len(json.loads(calls.read_text())) == 1
    assert report["attempts"][0]["tools"]["other"] == 1


def test_event_counters_use_whitelisted_skills_and_drop_tool_payloads(tmp_path, monkeypatch):
    root, temp = setup_runtime(tmp_path, monkeypatch)
    fake_cli(
        tmp_path,
        monkeypatch,
        "changed()\n"
        "emit({'type': 'tool_use', 'part': {'id': 'same', 'tool': 'read', 'state': {'status': 'running'}}})\n"
        f"emit({{'type': 'tool_use', 'part': {{'id': 'same', 'tool': 'read', 'state': {{'status': 'completed', 'output': {PRIVATE!r}}}}}}})\n"
        "emit({'type': 'tool_use', 'part': {'tool': 'skill', 'state': {'status': 'completed', 'input': {'name': 'superpowers:test-driven-development'}}}})\n"
        "emit({'type': 'tool_use', 'part': {'tool': 'skill', 'state': {'status': 'completed', 'input': {'id': PRIVATE}}}})\n"
        "valid()",
    )
    attempt = runner.run_generation(root, temp, "implement", FIRST)["attempts"][0]
    assert attempt["pending_tools"] == 0
    assert attempt["skills"]["test-driven-development"] == 1
    assert attempt["skills"]["other"] == 1
    diagnostics(temp)


@pytest.mark.parametrize(
    "mutation,expected",
    [
        ("Path('.gitignore').write_text('feature.py\\n')", "foreign_path_changed"),
        ("Path('foreign.py').write_text('secret\\n')", "foreign_path_changed"),
        (
            "Path('__pycache__').mkdir(); Path('__pycache__/hidden.py').write_text('secret')",
            "foreign_path_changed",
        ),
        ("Path('.opencode/agents/ai-task.md').write_text('broadened')", "agent_changed"),
        ("Path('.git/HEAD').write_text('f' * 40 + '\\n')", "head_changed"),
        (
            "Path('.git/config').write_text('[core]\\nfsmonitor = dangerous-command\\n')",
            "git_metadata_changed",
        ),
        ("Path('.git/objects/foreign').write_text('object tampering')", "git_metadata_changed"),
        ("Path('.git/logs/foreign').write_text('log tampering')", "git_metadata_changed"),
        ("Path('feature.py').unlink()", "file_deleted"),
        ("Path('feature.py').chmod(0o777)", "file_mode_changed"),
        ("Path('feature.py').write_bytes(b'bad\\x00data')", "unsafe_file"),
        (
            "Path('feature.py').unlink(); Path('feature.py').symlink_to('docs/feature.md')",
            "unsafe_file",
        ),
        ("Path('feature.py').unlink(); os.link('docs/feature.md', 'feature.py')", "unsafe_file"),
    ],
)
def test_policy_mutations_are_never_reset_or_retried(tmp_path, monkeypatch, mutation, expected):
    root, temp = setup_runtime(tmp_path, monkeypatch)
    calls = fake_cli(tmp_path, monkeypatch, mutation + "\nemit({'type': 'error'})")
    report = fails(root, temp, expected)
    assert len(json.loads(calls.read_text())) == 1
    assert report["attempts"][0].get("scoped_rollback") is None


def test_scope_input_tampering_cannot_authorize_fallback(tmp_path, monkeypatch):
    root, temp = setup_runtime(tmp_path, monkeypatch)
    calls = fake_cli(
        tmp_path,
        monkeypatch,
        f"Path({str(temp / 'task-context.json')!r}).write_text('{{}}')\nemit({{'type': 'error'}})",
    )
    fails(root, temp, "input_changed")
    assert len(json.loads(calls.read_text())) == 1


def test_repair_can_change_one_existing_file_without_required_test_again(tmp_path, monkeypatch):
    root, temp = setup_runtime(tmp_path, monkeypatch, mode="repair")
    fake_cli(tmp_path, monkeypatch, "Path('feature.py').write_text('value = 2\\n')\nvalid()")
    report = runner.run_generation(root, temp, "repair", FIRST)
    assert report["attempts"][0]["required_files"] == 1
    assert report["attempts"][0]["required_files_changed"] == 0
    assert json.loads((temp / "task-context.json").read_text())["attempt"] == 2


def test_repair_cannot_create_even_initially_approved_files(tmp_path, monkeypatch):
    scope = {
        "files": ["feature.py", "tests/test_new.py"],
        "create": ["tests/test_new.py"],
        "required": [],
    }
    root, temp = setup_runtime(tmp_path, monkeypatch, scope=scope, mode="repair")
    calls = fake_cli(
        tmp_path, monkeypatch, "Path('tests/test_new.py').write_text('assert True\\n')\nvalid()"
    )
    fails(root, temp, "new_file_forbidden", "repair")
    assert len(json.loads(calls.read_text())) == 1


def test_missing_required_files_is_not_a_success(tmp_path, monkeypatch):
    root, temp = setup_runtime(tmp_path, monkeypatch, second=False)
    fake_cli(tmp_path, monkeypatch, "Path('feature.py').write_text('value = 2\\n')\nvalid()")
    fails(root, temp, "required_missing")


def test_questions_or_final_text_without_changes_is_not_success(tmp_path, monkeypatch):
    root, temp = setup_runtime(tmp_path, monkeypatch, second=False)
    fake_cli(tmp_path, monkeypatch, "valid()")
    fails(root, temp, "no_changes")


def test_two_failed_models_do_not_get_a_third_attempt(tmp_path, monkeypatch):
    root, temp = setup_runtime(tmp_path, monkeypatch)
    calls = fake_cli(tmp_path, monkeypatch, "emit({'type': 'error'})")
    report = fails(root, temp, "provider_error")
    assert json.loads(calls.read_text()) == [FIRST, SECOND]
    assert len(report["attempts"]) == 2


@pytest.mark.parametrize(
    "change",
    [
        {"selected": "paid/provider-private-model"},
        {"task": "plan"},
        {"probes": [{"model": FIRST, "passed": False}]},
        {"probes": [{"model": FIRST, "passed": "true"}]},
        {"probes": [{"model": FIRST, "passed": True}, {"model": FIRST, "passed": False}]},
    ],
)
def test_router_selection_must_match_this_successful_probe(tmp_path, monkeypatch, change):
    root, temp = setup_runtime(tmp_path, monkeypatch)
    report = json.loads((temp / "model.json").read_text())
    report.update(change)
    (temp / "model.json").write_text(json.dumps(report))
    calls = fake_cli(tmp_path, monkeypatch, "changed()\nvalid()")
    result = fails(root, temp, "invalid_router_report")
    assert not calls.exists()
    assert "paid/provider-private-model" not in json.dumps(result)


def test_unknown_or_failed_alternate_never_becomes_fallback(tmp_path, monkeypatch):
    root, temp = setup_runtime(tmp_path, monkeypatch, second=False)
    report = json.loads((temp / "model.json").read_text())
    report["probes"].append({"model": PRIVATE, "passed": True})
    (temp / "model.json").write_text(json.dumps(report))
    calls = fake_cli(tmp_path, monkeypatch, "emit({'type': 'error'})")
    fails(root, temp, "provider_error")
    assert json.loads(calls.read_text()) == [FIRST]


def test_prompt_limit_is_bytes_not_characters_and_does_not_truncate(tmp_path, monkeypatch):
    root, temp = setup_runtime(tmp_path, monkeypatch)
    prompt = "\U0001f600" * 100_001
    (temp / "task-prompt.txt").write_text(prompt)
    calls = fake_cli(tmp_path, monkeypatch, "changed()\nvalid()")
    fails(root, temp, "prompt_limit")
    assert not calls.exists()
    assert (temp / "task-prompt.txt").read_text() == prompt


def test_invalid_input_json_still_creates_content_free_diagnostics(tmp_path, monkeypatch):
    root, temp = setup_runtime(tmp_path, monkeypatch)
    (temp / "task-context.json").write_text(PRIVATE)
    fails(root, temp, "invalid_context")


def test_unsafe_input_link_is_not_read(tmp_path, monkeypatch):
    root, temp = setup_runtime(tmp_path, monkeypatch)
    path = temp / "task-prompt.txt"
    path.unlink()
    path.symlink_to(root / "feature.py")
    fails(root, temp, "unsafe_file")


def test_unavailable_cli_has_safe_diagnostics(tmp_path, monkeypatch):
    root, temp = setup_runtime(tmp_path, monkeypatch)
    real = runner.subprocess.Popen

    def missing(command, *args, **kwargs):
        if command[0] == "opencode":
            raise OSError(PRIVATE)
        return real(command, *args, **kwargs)

    monkeypatch.setattr(runner.subprocess, "Popen", missing)
    fails(root, temp, "cli_unavailable")


def test_initial_dirty_file_is_not_silently_reset(tmp_path, monkeypatch):
    root, temp = setup_runtime(tmp_path, monkeypatch)
    (root / "feature.py").write_text("preexisting = 7\n")
    calls = fake_cli(tmp_path, monkeypatch, "changed()\nvalid()")
    fails(root, temp, "initial_changes")
    assert not calls.exists()
    assert (root / "feature.py").read_text() == "preexisting = 7\n"


def test_real_cli_entrypoint_uses_trusted_imports_and_no_credentials(tmp_path, monkeypatch):
    root, temp = setup_runtime(tmp_path, monkeypatch)
    monkeypatch.setenv("GITHUB_TOKEN", PRIVATE)
    monkeypatch.setenv("GH_TOKEN", PRIVATE)
    monkeypatch.setenv("OPENAI_API_KEY", PRIVATE)
    fake_cli(
        tmp_path,
        monkeypatch,
        "assert not any(key in os.environ for key in ('GITHUB_TOKEN', 'GH_TOKEN', 'OPENAI_API_KEY', 'RUNNER_TEMP'))\nchanged()\nvalid()",
    )
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            str(ROOT / "scripts/automation/generation_runner.py"),
            "--mode",
            "implement",
        ],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert result.returncode == 0, result.stderr
    assert PRIVATE not in result.stdout + result.stderr
    assert diagnostics(temp)["status"] == "success"


def test_production_budget_constants_cannot_be_changed_by_model_context():
    assert runner.MODE_LIMITS == {"implement": (1150.0, 1800.0), "repair": (750.0, 1000.0)}


@pytest.mark.parametrize("parent_exits", [True, False])
def test_detached_server_and_grandchild_are_dead_before_inspection(
    tmp_path, monkeypatch, parent_exits
):
    root, temp = setup_runtime(tmp_path, monkeypatch, second=False)
    monkeypatch.setattr(runner, "MODE_LIMITS", {"implement": (0.4, 0.9)})
    marker = tmp_path / "detached-writer"
    ready = tmp_path / "descendant-started"
    grandchild = (
        "import time; from pathlib import Path; "
        f"Path({str(ready)!r}).write_text('ready'); time.sleep(0.8); "
        f"Path({str(marker)!r}).write_text('bad')"
    )
    server = (
        "import subprocess, sys, time; "
        f"subprocess.Popen([sys.executable, '-c', {grandchild!r}], start_new_session=True); "
        "time.sleep(3)"
    )
    fake_cli(
        tmp_path,
        monkeypatch,
        f"subprocess.Popen([sys.executable, '-c', {server!r}], start_new_session=True, "
        "stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)\n"
        f"while not Path({str(ready)!r}).exists(): time.sleep(0.001)\n"
        + ("changed()\nvalid()" if parent_exits else "time.sleep(3)"),
    )
    if parent_exits:
        assert runner.run_generation(root, temp, "implement", FIRST)["status"] == "success"
    else:
        fails(root, temp, "timeout")
    assert ready.exists(), "The detached grandchild really started before cleanup"
    time.sleep(0.85)
    assert not marker.exists()


def test_preexisting_child_is_not_killed_by_attempt_cleanup(tmp_path, monkeypatch):
    root, temp = setup_runtime(tmp_path, monkeypatch)
    foreign = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(10)"])
    try:
        fake_cli(tmp_path, monkeypatch, "changed()\nvalid()")
        runner.run_generation(root, temp, "implement", FIRST)
        assert foreign.poll() is None
    finally:
        foreign.kill()
        foreign.wait(timeout=3)


def test_v2_projection_without_token_finish_is_accepted(tmp_path, monkeypatch):
    root, temp = setup_runtime(tmp_path, monkeypatch)
    fake_cli(
        tmp_path,
        monkeypatch,
        "changed()\nemit({'type': 'step_start'})\n"
        "emit({'type': 'text', 'part': {'text': PRIVATE}})",
    )
    report = runner.run_generation(root, temp, "implement", FIRST)
    assert report["attempts"][0]["terminal_finish_seen"] is False


def test_v2_final_projection_without_tokens_after_tool_step_is_accepted(tmp_path, monkeypatch):
    root, temp = setup_runtime(tmp_path, monkeypatch, second=False)
    calls = fake_cli(
        tmp_path,
        monkeypatch,
        "changed()\nemit({'type': 'step_start'})\n"
        "emit({'type': 'text', 'part': {'text': 'Working.'}})\n"
        "emit({'type': 'tool_use', 'part': {'id': 'read-1', 'tool': 'read', 'state': "
        "{'status': 'completed', 'input': {'filePath': 'feature.py'}}}})\n"
        "emit({'type': 'step_finish', 'part': {'reason': 'tool-calls'}})\n"
        "emit({'type': 'step_start'})\n"
        "emit({'type': 'text', 'part': {'text': 'Completed.'}})",
    )
    attempt = runner.run_generation(root, temp, "implement", FIRST)["attempts"][0]
    assert attempt["pending_tools"] == 0
    assert attempt["terminal_finish_seen"] is False
    assert json.loads(calls.read_text()) == [FIRST]


def test_v2_new_step_cannot_inherit_text_or_terminal_finish(tmp_path, monkeypatch):
    root, temp = setup_runtime(tmp_path, monkeypatch, second=False)
    fake_cli(
        tmp_path,
        monkeypatch,
        "changed()\nemit({'type': 'step_start'})\nvalid()\n" "emit({'type': 'step_start'})",
    )
    attempt = fails(root, temp, "empty_response")["attempts"][0]
    assert attempt["terminal_finish_seen"] is False


@pytest.mark.parametrize(
    "prior_event,expected",
    [
        (
            {
                "type": "tool_use",
                "part": {"id": "read-1", "tool": "read", "state": {"status": "running"}},
            },
            "incomplete_tools",
        ),
        ({"type": "step_finish", "part": {"reason": "length"}}, "output_truncated"),
        ({"type": "error", "error": {"type": "unknown", "message": PRIVATE}}, "provider_error"),
        ({"type": "question"}, "tool_policy"),
    ],
)
def test_v2_new_step_preserves_pending_tools_and_sticky_failures(tmp_path, prior_event, expected):
    metrics = runner.EventMetrics(tmp_path, {"files": ["feature.py"], "create": [], "required": []})
    sequence = [
        {"type": "step_start"},
        prior_event,
        {"type": "step_start"},
        {"type": "text", "part": {"text": "Completed."}},
    ]
    metrics.feed("".join(json.dumps(event) + "\n" for event in sequence).encode())
    assert metrics.finish() == expected


def test_v2_native_patch_and_skill_id_use_existing_permissions(tmp_path, monkeypatch):
    root, temp = setup_runtime(tmp_path, monkeypatch)
    patch = (
        "*** Begin Patch\n*** Update File: feature.py\n@@\n-value = 0\n+value = 1\n*** End Patch"
    )
    fake_cli(
        tmp_path,
        monkeypatch,
        f"patch = {patch!r}\n"
        "emit({'type': 'tool_use', 'part': {'id': 'patch-1', 'tool': 'patch', 'state': "
        "{'status': 'completed', 'input': {'patchText': patch}, 'output': PRIVATE}}})\n"
        "emit({'type': 'tool_use', 'part': {'id': 'skill-1', 'tool': 'skill', 'state': "
        "{'status': 'completed', 'input': {'id': 'superpowers:test-driven-development'}}}})\n"
        "changed()\nvalid()",
    )
    report = runner.run_generation(root, temp, "implement", FIRST)
    assert report["attempts"][0]["tools"]["patch"] == 1
    assert report["attempts"][0]["skills"]["test-driven-development"] == 1


@pytest.mark.parametrize(
    "header",
    [
        "*** Update File: foreign.py",
        "*** Add File: foreign.py",
        "*** Delete File: feature.py",
        "*** Move to: feature.py",
    ],
)
def test_native_patch_cannot_request_foreign_paths_deletes_or_moves(tmp_path, monkeypatch, header):
    root, temp = setup_runtime(tmp_path, monkeypatch)
    calls = fake_cli(
        tmp_path,
        monkeypatch,
        f"patch = '*** Begin Patch\\n' + {header!r} + '\\n*** End Patch'\n"
        "emit({'type': 'tool_use', 'part': {'id': 'patch-1', 'tool': 'patch', 'state': "
        "{'status': 'error', 'input': {'patchText': patch}, 'error': PRIVATE}}})\nvalid()",
    )
    fails(root, temp, "tool_policy")
    assert json.loads(calls.read_text()) == [FIRST]


def test_allowed_tool_error_can_be_recovered_before_final_text(tmp_path, monkeypatch):
    root, temp = setup_runtime(tmp_path, monkeypatch)
    calls = fake_cli(
        tmp_path,
        monkeypatch,
        "emit({'type': 'tool_use', 'part': {'id': 'read-1', 'tool': 'read', 'state': "
        "{'status': 'error', 'input': {'filePath': 'optional-file'}, 'error': PRIVATE}}})\n"
        "changed()\nvalid()",
    )
    report = runner.run_generation(root, temp, "implement", FIRST)
    assert report["attempts"][0]["tool_errors"] == 1
    assert json.loads(calls.read_text()) == [FIRST]


def test_native_v2_provider_error_with_zero_exit_is_not_success(tmp_path, monkeypatch):
    root, temp = setup_runtime(tmp_path, monkeypatch, second=False)
    fake_cli(
        tmp_path,
        monkeypatch,
        "changed()\nvalid()\nemit({'type': 'error', 'error': {'type': 'unknown', 'message': PRIVATE}})",
    )
    attempt = fails(root, temp, "provider_error")["attempts"][0]
    assert attempt["exit_code"] == 0
    assert attempt["provider_http_status"] == 0


def test_large_unicode_prompt_uses_stdin_without_argv_limit(tmp_path, monkeypatch):
    root, temp = setup_runtime(tmp_path, monkeypatch)
    prompt = "\U0001f600" * 68_000
    (temp / "task-prompt.txt").write_text(prompt)
    fake_cli(
        tmp_path,
        monkeypatch,
        "assert len(sys.argv) == 10\n"
        "assert sys.stdin.read() == '\\U0001f600' * 68_000\nchanged()\nvalid()",
    )
    assert runner.run_generation(root, temp, "implement", FIRST)["status"] == "success"
    assert "\U0001f600" not in (temp / "generation-diagnostics.json").read_text()


def test_obvious_line_limit_is_rejected_before_diff_matching(tmp_path, monkeypatch):
    root, temp = setup_runtime(tmp_path, monkeypatch)

    def prohibit_matcher(*args, **kwargs):
        raise AssertionError("oversized line delta must not reach quadratic matching")

    monkeypatch.setattr(runner.difflib, "SequenceMatcher", prohibit_matcher)
    calls = fake_cli(
        tmp_path,
        monkeypatch,
        "Path('feature.py').write_text('x\\n' * 148_000)\nvalid()",
    )
    fails(root, temp, "candidate_limit")
    assert json.loads(calls.read_text()) == [FIRST]


def test_output_event_limit_cannot_be_hidden_by_provider_error(tmp_path, monkeypatch):
    root, temp = setup_runtime(tmp_path, monkeypatch, second=False)
    monkeypatch.setattr(runner, "MAX_EVENTS", 1)
    fake_cli(
        tmp_path,
        monkeypatch,
        "emit({'type': 'step_start'})\nemit({'type': 'error', 'error': {'message': PRIVATE}})",
    )
    fails(root, temp, "output_limit")


def test_cleanup_failure_still_closes_streams_and_restores_subreaper(tmp_path, monkeypatch):
    root, temp = setup_runtime(tmp_path, monkeypatch)
    real_stop, real_close = runner.ProcessBoundary.stop, runner.ProcessBoundary.close
    processes, closed = [], []

    def failed_stop(self, process):
        real_stop(self, process)
        processes.append(process)
        raise runner.GenerationError("process_cleanup")

    def observed_close(self):
        real_close(self)
        closed.append(True)

    monkeypatch.setattr(runner.ProcessBoundary, "stop", failed_stop)
    monkeypatch.setattr(runner.ProcessBoundary, "close", observed_close)
    calls = fake_cli(tmp_path, monkeypatch, "changed()\nvalid()")
    fails(root, temp, "process_cleanup")
    assert json.loads(calls.read_text()) == [FIRST]
    assert closed == [True]
    assert processes and all(
        stream.closed
        for process in processes
        for stream in (process.stdin, process.stdout, process.stderr)
    )
