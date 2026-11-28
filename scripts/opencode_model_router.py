#!/usr/bin/env python3
"""Select a working, approved free OpenCode model for the current CI task.

The router NEVER tries an arbitrary model from the catalog: discovery is
intersected with a small, reviewed free-model allowlist. A bounded, read-only
tool-use probe measures functionality and basic repository understanding.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from automation import free_providers, task_probe  # noqa: E402
from automation.provider_policy import classify, permits_fallback  # noqa: E402

# Audited 2026-11-28 against the official free-model pricing/privacy catalog:
# both are free, zero-retention and no-training. Live probes still must pass.
APPROVED_FREE_MODELS = (
    "opencode/hy4-flash-free",
    "opencode/deepseek-v4.1-flash-free",
)
ALL_APPROVED_MODELS = APPROVED_FREE_MODELS + free_providers.OPENROUTER_MODELS
TASKS = ("plan", "implement", "repair")
DISCOVERY_TIMEOUT = 50
PROBE_TIMEOUT = 110
MAX_CAPTURE = 1_500_000
MODEL_LINE = re.compile(r"^opencode/[a-z0-9][a-z0-9.-]*-free$")
CATALOG_LINE = re.compile(r"^[a-z0-9][a-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._:/-]*$")
MARKER = re.compile(r"(?m)^ROUTER_OK\s*$")
DISCOVERY_FAILURES = {
    "empty_catalog",
    "no_approved_models",
    "discovery_timeout",
    "discovery_cli_error",
    "discovery_output_limit",
    "discovery_invalid_output",
}


class RouterError(RuntimeError):
    """Only fixed controller-owned codes may leave a failed command."""

    def __init__(self, code: str) -> None:
        self.code = code if code in DISCOVERY_FAILURES else "router_error"
        super().__init__(self.code)


def byte_count(value: Any) -> int:
    if isinstance(value, bytes):
        return len(value)
    return len(value.encode("utf-8")) if isinstance(value, str) else 0


def isolated_environment(model: str | None = None) -> dict[str, str]:
    """Give the model no GitHub token, provider key or unrelated credentials."""
    allowed = (
        "PATH",
        "HOME",
        "USER",
        "LANG",
        "LC_ALL",
        "TMPDIR",
        "XDG_CONFIG_HOME",
        "XDG_CACHE_HOME",
        "XDG_DATA_HOME",
        "TERM",
    )
    environment = {key: os.environ[key] for key in allowed if key in os.environ}
    environment["CI"] = "true"
    return free_providers.credentials(environment, model)


def parse_catalog(stdout: str) -> set[str]:
    """Use exact, full-line IDs; never trust substring/free text matches."""
    return {line.strip() for line in stdout.splitlines() if MODEL_LINE.fullmatch(line.strip())}


def discover_models(
    diagnostics: dict[str, Any] | None = None,
    *,
    timeout: float = DISCOVERY_TIMEOUT,
    max_attempts: int = 2,
) -> set[str]:
    """Use V2's native catalog command, with at most one fresh retry.

    No catalog text, unapproved model identifiers, stderr or exception strings
    enter diagnostics. An unusable catalog gets one fresh attempt because V2
    can initially serve its bundled catalog while refreshing it asynchronously.
    """
    environment = isolated_environment()
    trace = diagnostics if diagnostics is not None else {}
    trace.update(attempts=[], catalog_count=0, approved_count=0, status="failure")
    code = "empty_catalog"
    for number in range(1, max_attempts + 1):
        start = time.monotonic()
        record: dict[str, Any] = {
            "attempt": number,
            "exit_code": None,
            "stdout_bytes": 0,
            "stderr_bytes": 0,
            "catalog_count": 0,
            "approved_count": 0,
        }
        approved: set[str] = set()
        try:
            result = subprocess.run(
                ["opencode", "models", "--standalone"],
                input="",
                capture_output=True,
                text=True,
                check=False,
                timeout=timeout,
                env=environment,
            )
        except subprocess.TimeoutExpired as error:
            code = "discovery_timeout"
            record.update(
                stdout_bytes=byte_count(error.output), stderr_bytes=byte_count(error.stderr)
            )
        except OSError:
            code = "discovery_cli_error"
        except UnicodeError:
            code = "discovery_invalid_output"
        else:
            record.update(
                exit_code=result.returncode,
                stdout_bytes=byte_count(result.stdout),
                stderr_bytes=byte_count(getattr(result, "stderr", "")),
            )
            if result.returncode != 0:
                code = "discovery_cli_error"
            elif record["stdout_bytes"] + record["stderr_bytes"] > MAX_CAPTURE:
                code = "discovery_output_limit"
            else:
                catalog = {
                    line.strip()
                    for line in result.stdout.splitlines()
                    if CATALOG_LINE.fullmatch(line.strip())
                }
                approved = parse_catalog(result.stdout) & set(APPROVED_FREE_MODELS)
                record.update(catalog_count=len(catalog), approved_count=len(approved))
                code = (
                    "catalog_ready"
                    if approved
                    else "no_approved_models" if catalog else "empty_catalog"
                )
        record.update(code=code, elapsed_seconds=round(time.monotonic() - start, 2))
        trace["attempts"].append(record)
        trace.update(
            code=code,
            catalog_count=record["catalog_count"],
            approved_count=len(approved),
            status="success" if approved else "failure",
        )
        print(
            f"Router discovery: attempt={number}, code={code}, exit_code={record['exit_code']}, "
            f"catalog_count={record['catalog_count']}, approved_count={len(approved)}, "
            f"seconds={record['elapsed_seconds']}",
            flush=True,
        )
        if approved:
            return approved
        if code in {"discovery_output_limit", "discovery_invalid_output"}:
            break
    if code in {"empty_catalog", "no_approved_models"}:
        return set()
    raise RouterError(code)


def probe_prompt(task: str) -> str:
    """Benchmark a small, fixed factual task with actual read/skill tools."""
    if task not in TASKS:
        raise ValueError("Invalid router task")
    focus = {
        "plan": "You are choosing a model for planning an issue.",
        "implement": "You are choosing a model for an approved implementation.",
        "repair": "You are choosing a model for repairing a failing implementation.",
    }[task]
    return (
        f"{focus} This is only a read-only CI probe, not an issue task. "
        "Use the skill tool to load Superpowers brainstorming. Read AGENTS.md. "
        "Only after both tools succeed, write a standalone line exactly ROUTER_OK "
        "and one short sentence identifying knx_to_openhab and its two output "
        "formats, legacy and yaml. If any tool fails, do not write ROUTER_OK. "
        "Never edit a file, run shell commands or start subagents." + task_probe.prompt(task)
    )


def inspect_events(output: str, task: str, seconds: float) -> dict[str, Any]:
    """Score observable tool use, a small fact check and elapsed seconds."""
    successful_tools = set()
    pending = set()
    texts = []
    event_count = invalid = provider_errors = tool_errors = 0
    incomplete = False
    policy: dict[str, Any] = {
        "provider_failure": "none",
        "provider_http_status": 0,
        "retry_after_seconds": 0,
    }
    for line in output.splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except (TypeError, ValueError, RecursionError):
            invalid += 1
            continue
        if not isinstance(event, dict) or not isinstance(event.get("type"), str):
            invalid += 1
            continue
        event_count += 1
        kind = event["type"]
        if kind == "error":
            provider_errors += 1
            if permits_fallback(policy):
                policy = classify(event.get("error"))
        if kind in {"question", "permission", "permission_request"}:
            incomplete = True
        part = event.get("part")
        if not isinstance(part, dict):
            continue
        if kind == "text" and isinstance(part.get("text"), str):
            texts.append(part["text"])
        if kind == "step_finish" and part.get("reason") in ("length", "max_tokens", "max_steps"):
            incomplete = True
        if kind == "tool_use":
            state = part.get("state") or {}
            if not isinstance(state, dict):
                invalid += 1
                continue
            tool, status = part.get("tool"), state.get("status")
            identity = str(part.get("id") or part.get("callID") or tool)
            if status in ("streaming", "pending", "running"):
                pending.add(identity)
            elif status in ("completed", "error"):
                pending.discard(identity)
                tool_errors += int(status == "error")
                if status == "completed" and tool in ("read", "skill"):
                    successful_tools.add(tool)
            else:
                invalid += 1
            if tool not in ("read", "skill", "glob", "grep"):
                incomplete = True
    answer = "\n".join(texts)
    marker_ok = bool(MARKER.search(answer))
    capability = task_probe.assess(answer, task)
    passed = successful_tools == {"read", "skill"} and marker_ok and capability["task_correct"]
    code = (
        "provider_error"
        if provider_errors
        else (
            "invalid_events"
            if invalid
            else (
                "incomplete_probe"
                if pending or tool_errors or incomplete or not passed
                else "probe_passed"
            )
        )
    )
    passed = code == "probe_passed"
    factual = (
        "legacy" in answer.casefold()
        and "yaml" in answer.casefold()
        and ("knx_to_openhab" in answer.casefold() or "knx to openhab" in answer.casefold())
    )
    # Correct task results and safe tool use are mandatory. Factual quality
    # outweighs the entire speed bonus; latency cannot redeem a wrong answer.
    score = 0
    if passed:
        speed_bonus = max(0, 9 - int(seconds / 10))
        score = 100 + (20 if factual else 0) + speed_bonus
    return {
        "passed": passed,
        "code": code,
        "factual": factual,
        "read_ok": "read" in successful_tools,
        "skill_ok": "skill" in successful_tools,
        "elapsed_seconds": round(seconds, 2),
        "score": score,
        "marker_ok": marker_ok,
        "event_count": event_count,
        "invalid_event_lines": invalid,
        "provider_errors": provider_errors,
        "tool_errors": tool_errors,
        "pending_tools": len(pending),
        **capability,
        **policy,
    }


def probe_model(model: str, task: str, *, timeout: float = PROBE_TIMEOUT) -> dict[str, Any]:
    if model not in ALL_APPROVED_MODELS:
        raise ValueError("Model is not approved")
    start = time.monotonic()
    cmd = [
        "opencode",
        "run",
        "--standalone",
        "--archived",
        "--format",
        "json",
        "--agent",
        "ci-smoke",
        "--model",
        model,
        probe_prompt(task),
    ]
    try:
        result = subprocess.run(
            cmd,
            input="",
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
            env=isolated_environment(model),
        )
    except subprocess.TimeoutExpired as error:
        return {
            "model": model,
            "passed": False,
            "code": "timeout",
            "score": 0,
            "elapsed_seconds": round(time.monotonic() - start, 2),
            "exit_code": None,
            "stdout_bytes": byte_count(error.output),
            "stderr_bytes": byte_count(error.stderr),
        }
    except (OSError, UnicodeError):
        return {
            "model": model,
            "passed": False,
            "code": "cli_error",
            "score": 0,
            "elapsed_seconds": round(time.monotonic() - start, 2),
            "exit_code": None,
            "stdout_bytes": 0,
            "stderr_bytes": 0,
        }
    elapsed = time.monotonic() - start
    stdout_bytes = byte_count(result.stdout)
    stderr_bytes = byte_count(getattr(result, "stderr", ""))
    metadata = {
        "model": model,
        "elapsed_seconds": round(elapsed, 2),
        "exit_code": result.returncode,
        "stdout_bytes": stdout_bytes,
        "stderr_bytes": stderr_bytes,
    }
    if stdout_bytes + stderr_bytes > MAX_CAPTURE:
        return {**metadata, "passed": False, "code": "output_limit", "score": 0}
    inspected = inspect_events(result.stdout, task, elapsed)
    if result.returncode != 0:
        inspected.update(
            passed=False,
            code="provider_error" if inspected["provider_errors"] else "cli_error",
            score=0,
        )
    return {**metadata, **inspected}


def rank_models(probes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    acceptable = [
        probe
        for probe in probes
        if isinstance(probe, dict)
        and probe.get("model") in ALL_APPROVED_MODELS
        and probe.get("passed") is True
    ]
    # The allowlist order is a stable tie-breaker; scores derive from this run.
    return sorted(
        acceptable,
        key=lambda probe: (
            probe.get("score", 0) if type(probe.get("score", 0)) is int else 0,
            -ALL_APPROVED_MODELS.index(probe["model"]),
        ),
        reverse=True,
    )


def choose_model(probes: list[dict[str, Any]]) -> dict[str, Any]:
    ranked = rank_models(probes)
    if not ranked:
        raise RuntimeError("No approved free model passed the task/read/skill probe")
    return ranked[0]


def write_summary(
    task: str,
    models: list[dict[str, Any]],
    selected: str | None,
    *,
    discovery: dict[str, Any] | None = None,
    failure_code: str | None = None,
) -> None:
    target = os.environ.get("GITHUB_STEP_SUMMARY")
    if not target:
        return
    lines = [
        "### OpenCode free-model router",
        "",
        f"Task: `{task}`. Only reviewed free models with enforced provider policy are eligible.",
        "",
        f"Result: `{failure_code or 'selected'}`.",
        "",
        "| Discovery attempt | Code | Catalog entries | Approved entries | Seconds |",
        "|---:|---|---:|---:|---:|",
    ]
    for attempt in (discovery or {}).get("attempts", []):
        lines.append(
            f"| {attempt['attempt']} | `{attempt['code']}` | {attempt['catalog_count']} | "
            f"{attempt['approved_count']} | {attempt['elapsed_seconds']} |"
        )
    lines.extend(
        [
            "",
            "| Candidate | Probe code | Task check | Fact check | Seconds | Score |",
            "|---|---|---|---|---:|---:|",
        ]
    )
    for model in models:
        lines.append(
            "| `{}` | {} | {} | {} | {} | {} |".format(
                model["model"],
                model.get("code", "probe_passed" if model.get("passed") else "incomplete_probe"),
                "pass" if model.get("task_correct") else "fail",
                "pass" if model.get("factual") else "n/a",
                model.get("elapsed_seconds", "n/a"),
                model.get("score", 0),
            )
        )
    lines.extend(
        ["", f"**Selected:** `{selected}`" if selected else "**No eligible model passed.**"]
    )
    with Path(target).open("a", encoding="utf-8") as out:
        out.write("\n".join(lines) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("select", choices=["select"])
    parser.add_argument("--task", choices=TASKS, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    discovery: dict[str, Any] = {"attempts": [], "catalog_count": 0, "approved_count": 0}
    report: dict[str, Any] = {
        "schema_version": 1,
        "task": args.task,
        "status": "failure",
        "failure_code": None,
        "available": [],
        "selected": None,
        "ranked": [],
        "probes": [],
        "discovery": discovery,
    }
    try:
        # One provider's discovery failure cannot suppress an independent route.
        try:
            available = discover_models(discovery)
        except RouterError:
            available = set()
        external: dict[str, Any] = {}
        report["openrouter_discovery"] = external
        available |= free_providers.discover(external)
        # Never probe other providers, paid IDs or newly advertised free IDs.
        ordered = [model for model in ALL_APPROVED_MODELS if model in available]
        report["available"] = ordered
        if not ordered:
            report["failure_code"] = discovery.get("code", "no_approved_models")
        else:
            for model in ordered:
                probe = probe_model(model, args.task, timeout=60)
                report["probes"].append(probe)
                code = probe.get(
                    "code", "probe_passed" if probe.get("passed") else "incomplete_probe"
                )
                print(
                    f"Router probe: model={model}, code={code}, passed={probe.get('passed') is True}, "
                    f"read_ok={probe.get('read_ok') is True}, skill_ok={probe.get('skill_ok') is True}, "
                    f"seconds={probe.get('elapsed_seconds', 0)}, exit_code={probe.get('exit_code')}",
                    flush=True,
                )
            try:
                report["selected"] = choose_model(report["probes"])["model"]
                report["ranked"] = [probe["model"] for probe in rank_models(report["probes"])]
                report["status"] = "success"
            except RuntimeError:
                report["failure_code"] = "probe_failed"
    except RouterError as error:
        report["failure_code"] = error.code
    except Exception:
        # Internal I/O/decoder failures must not leak model text in a traceback.
        report["failure_code"] = "router_error"
    try:
        args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    except OSError:
        print("::error::OpenCode model router stopped: report_write_error", file=sys.stderr)
        return 1
    try:
        write_summary(
            args.task,
            report["probes"],
            report["selected"],
            discovery=discovery,
            failure_code=report["failure_code"],
        )
    except OSError:
        print("::warning::OpenCode model router summary_write_error", file=sys.stderr)
    if report["status"] != "success":
        print(f"::error::OpenCode model router stopped: {report['failure_code']}", file=sys.stderr)
        return 1
    output = os.environ.get("GITHUB_OUTPUT")
    try:
        if output:
            with Path(output).open("a", encoding="utf-8") as target:
                target.write(f"model={report['selected']}\n")
    except OSError:
        report.update(status="failure", failure_code="output_write_error", selected=None)
        try:
            args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        except OSError:
            pass
        print("::error::OpenCode model router stopped: output_write_error", file=sys.stderr)
        return 1
    print(f"Selected approved free model for {args.task}: {report['selected']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
