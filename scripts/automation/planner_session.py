"""Private, source-bound OpenCode sessions and content-free progress observations."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from opencode_model_router import isolated_environment

from .model_response import MAX_EVENT_BYTES, ModelResponseError


def environment(state: Path | None = None) -> dict[str, str]:
    result = isolated_environment()
    # CLI 2.3.0 resolves its directory from PWD before process.cwd().
    result["PWD"] = str(Path.cwd().resolve())
    if state is not None:
        result["XDG_DATA_HOME"] = str(state.resolve())
    return result


def binding(temp: Path) -> str:
    """Bind history to checkout, tracked contents, request, policy and collected evidence."""
    digest = hashlib.sha256(str(Path.cwd().resolve()).encode())
    for args in (["rev-parse", "HEAD"], ["diff", "--no-ext-diff", "HEAD", "--"]):
        try:
            value = subprocess.run(
                ["git", *args], capture_output=True, check=True, timeout=10
            ).stdout
        except (OSError, subprocess.SubprocessError):
            raise ModelResponseError("context_changed") from None
        digest.update(value)
    for name in ("issue-prompt.txt", "issue-decision.json"):
        digest.update((temp / name).read_bytes())
    evidence = Path(".planner-evidence")
    if evidence.exists():
        for source in sorted(evidence.glob("*.txt")):
            digest.update(source.name.encode())
            digest.update(source.read_bytes())
    return digest.hexdigest()


def evidence_paths(temp: Path) -> set[str]:
    manifest = temp / "planning-context.json"
    if not manifest.exists():
        return set()
    context = json.loads(manifest.read_text(encoding="utf-8"))
    return {
        str(Path(source["file"]).resolve())
        for source in context.get("evidence", {}).get("sources", [])
        if source.get("status") == "available"
    }


def evidence_reads(output: str, paths: set[str]) -> set[str]:
    seen = set()
    for line in output.splitlines():
        try:
            event = json.loads(line)
            part = event.get("part", {})
            state = part.get("state", {})
            if event.get("type") != "tool_use" or part.get("tool") != "read":
                continue
            if state.get("status") != "completed":
                continue
            value = state.get("input", {}).get("filePath") or state.get("input", {}).get("path")
            if isinstance(value, str) and str(Path(value).resolve()) in paths:
                seen.add(str(Path(value).resolve()))
        except (ValueError, TypeError, AttributeError, OSError):
            continue
    return seen


def verify(session: str, state: Path, model: str, timeout: float) -> None:
    """Never let --session silently recreate missing history or resume another checkout."""
    try:
        with tempfile.TemporaryFile() as output:
            process = subprocess.Popen(
                ["opencode", "api", "--standalone", "GET", f"/api/session/{session}"],
                stdin=subprocess.DEVNULL,
                stdout=output,
                stderr=subprocess.DEVNULL,
                env=environment(state),
                start_new_session=True,
            )
            try:
                process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                stop(process, 0)
                raise ModelResponseError("resume_unavailable") from None
            output.seek(0)
            raw = output.read(64_001)
            if process.returncode or len(raw) > 64_000:
                raise ModelResponseError("resume_unavailable")
            info = json.loads(raw)
        provider, model_id = model.split("/", 1)
        if (
            info.get("id") != session
            or info.get("parentID")
            or info.get("permissions")
            or info.get("agent") != "issue-planner"
            or info.get("model", {}).get("providerID") != provider
            or info.get("model", {}).get("id") != model_id
            or Path(info["location"]["directory"]).resolve() != Path.cwd().resolve()
        ):
            raise ModelResponseError("resume_unavailable")
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        raise ModelResponseError("resume_unavailable") from None


def stop(process: subprocess.Popen, grace: float) -> bool:
    """Let the CLI interrupt and persist its session before killing the process tree."""
    import signal

    try:
        process.send_signal(signal.SIGTERM)
        process.wait(timeout=grace)
        return True
    except ProcessLookupError:
        return True
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=5)
        return False


def observations(output: str, expected_session: str | None = None) -> dict[str, Any]:
    """Inspect even timed-out output. Do not retain paths, replies, IDs or provider messages."""
    stats: dict[str, Any] = {
        "event_count": 0,
        "invalid_event_lines": 0,
        "completed_reads": 0,
        "completed_searches": 0,
        "completed_skills": 0,
        "completed_steps": 0,
        "tool_errors": 0,
        "provider_retries": 0,
        "retry_wait_seconds": 0,
        "error_events": 0,
        "session_mismatch": False,
        "input_tokens": 0,
        "output_tokens": 0,
    }
    for line in output[:MAX_EVENT_BYTES].splitlines():
        try:
            event = json.loads(line)
            if not isinstance(event, dict):
                raise ValueError
        except ValueError:
            stats["invalid_event_lines"] += 1
            continue
        stats["event_count"] += 1
        if expected_session and event.get("sessionID") != expected_session:
            stats["session_mismatch"] = True
        part = event.get("part")
        part = part if isinstance(part, dict) else {}
        kind = event.get("type")
        if kind == "error":
            stats["error_events"] += 1
        if kind == "tool_use":
            state = part.get("state") or {}
            if not isinstance(state, dict):
                continue
            if state.get("status") == "error":
                stats["tool_errors"] += 1
            if state.get("status") == "completed":
                tool = part.get("tool")
                key = {
                    "read": "completed_reads",
                    "grep": "completed_searches",
                    "glob": "completed_searches",
                    "skill": "completed_skills",
                }.get(tool if isinstance(tool, str) else "")
                if key:
                    stats[key] += 1
        if kind == "step_finish":
            stats["completed_steps"] += 1
            tokens = part.get("tokens") or {}
            if isinstance(tokens, dict):
                for field in ("input", "output"):
                    number = tokens.get(field)
                    if type(number) is int and 0 <= number <= 100_000_000:
                        stats[f"{field}_tokens"] += number
        if kind == "retry":
            stats["provider_retries"] += 1
            at, timestamp = event.get("nextRetryAt"), event.get("timestamp")
            if (
                isinstance(at, (int, float))
                and isinstance(timestamp, (int, float))
                and 0 <= at <= 10**15
                and 0 <= timestamp <= 10**15
            ):
                stats["retry_wait_seconds"] += min(3600, max(0, int((at - timestamp) / 1000)))
    return stats
