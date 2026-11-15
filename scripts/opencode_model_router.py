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

# Both models are free (as of 2026-11-15), worked in our anonymous CI smoke,
# and have an explicit zero-retention statement in the OpenCode model catalog.
APPROVED_FREE_MODELS = (
    "opencode/glm-5.3-flash-free",
    "opencode/deepseek-v4.1-flash-free",
)
TASKS = ("plan", "implement")
DISCOVERY_TIMEOUT = 50
PROBE_TIMEOUT = 110
MAX_CAPTURE = 1_500_000
MODEL_LINE = re.compile(r"^opencode/[a-z0-9][a-z0-9.-]*-free$")
MARKER = re.compile(r"(?m)^ROUTER_OK\s*$")


def isolated_environment() -> dict[str, str]:
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
    return environment


def parse_catalog(stdout: str) -> set[str]:
    """Use exact, full-line IDs; never trust substring/free text matches."""
    return {
        line.strip()
        for line in stdout.splitlines()
        if MODEL_LINE.fullmatch(line.strip())
    }


def discover_models() -> set[str]:
    environment = isolated_environment()
    errors = []
    for cmd in (["opencode", "models", "opencode", "--refresh"], ["opencode", "models"]):
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False,
                timeout=DISCOVERY_TIMEOUT,
                env=environment,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            errors.append(type(exc).__name__)
            continue
        if result.returncode == 0:
            # An empty catalog is not an excuse to select a cached or paid model.
            return parse_catalog(result.stdout) & set(APPROVED_FREE_MODELS)
        errors.append(f"catalog command exit status {result.returncode}")
    raise RuntimeError("OpenCode model discovery failed: " + ", ".join(errors))


def probe_prompt(task: str) -> str:
    """Benchmark a small, fixed factual task with actual read/skill tools."""
    if task not in TASKS:
        raise ValueError("Invalid router task")
    focus = (
        "You are choosing a model for planning an issue."
        if task == "plan"
        else "You are choosing a model for an approved README-only implementation."
    )
    return (
        f"{focus} This is only a read-only CI probe, not an issue task. "
        "Use the skill tool to load Superpowers brainstorming. Read AGENTS.md. "
        "Only after both tools succeed, write a standalone line exactly ROUTER_OK "
        "and one short sentence identifying knx_to_openhab and its two output "
        "formats, legacy and yaml. If any tool fails, do not write ROUTER_OK. "
        "Never edit a file, run shell commands or start subagents."
    )


def inspect_events(output: str, task: str, seconds: float) -> dict[str, Any]:
    """Score observable tool use, a small fact check and elapsed seconds."""
    successful_tools = set()
    texts = []
    for line in output.splitlines():
        try:
            event = json.loads(line)
        except (TypeError, ValueError):
            continue
        if not isinstance(event, dict):
            continue
        part = event.get("part")
        if not isinstance(part, dict):
            continue
        if event.get("type") == "text" and isinstance(part.get("text"), str):
            texts.append(part["text"])
        if event.get("type") == "tool_use":
            state = part.get("state") or {}
            if isinstance(state, dict) and state.get("status") == "completed":
                if part.get("tool") in ("read", "skill"):
                    successful_tools.add(part["tool"])
    answer = "\n".join(texts)
    passed = successful_tools == {"read", "skill"} and bool(MARKER.search(answer))
    factual = (
        "legacy" in answer.casefold()
        and "yaml" in answer.casefold()
        and ("knx_to_openhab" in answer.casefold() or "knx to openhab" in answer.casefold())
    )
    # A live agent-tool probe is not a rigorous coding benchmark. Give priority
    # to correct tool use, then the factual check, and only then speed.
    score = 0
    if passed:
        speed_bonus = max(0, 20 - int(seconds / 3))
        score = 70 + (20 if factual else 0) + speed_bonus
        # Small tie-breaker backed by the actual issue #96 end-to-end runs.
        if task == "implement":
            score += 2
    return {
        "passed": passed,
        "factual": factual,
        "read_ok": "read" in successful_tools,
        "skill_ok": "skill" in successful_tools,
        "elapsed_seconds": round(seconds, 2),
        "score": score,
    }


def probe_model(model: str, task: str) -> dict[str, Any]:
    if model not in APPROVED_FREE_MODELS:
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
            timeout=PROBE_TIMEOUT,
            env=isolated_environment(),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            "model": model,
            "passed": False,
            "reason": type(exc).__name__,
            "elapsed_seconds": round(time.monotonic() - start, 2),
            "score": 0,
        }
    elapsed = time.monotonic() - start
    if result.returncode != 0:
        return {
            "model": model,
            "passed": False,
            "reason": f"OpenCode exit status {result.returncode}",
            "elapsed_seconds": round(elapsed, 2),
            "score": 0,
        }
    if len(result.stdout.encode("utf-8")) > MAX_CAPTURE:
        return {
            "model": model,
            "passed": False,
            "reason": "Probe event log exceeds size cap",
            "elapsed_seconds": round(elapsed, 2),
            "score": 0,
        }
    return {"model": model, **inspect_events(result.stdout, task, elapsed)}


def choose_model(probes: list[dict[str, Any]]) -> dict[str, Any]:
    acceptable = [
        probe
        for probe in probes
        if probe.get("model") in APPROVED_FREE_MODELS and probe.get("passed") is True
    ]
    if not acceptable:
        raise RuntimeError("No approved free model passed the read/skill probe")
    # The allowlist order is a stable tie-breaker; scores derive from this run.
    return max(
        acceptable,
        key=lambda probe: (
            float(probe["score"]),
            -APPROVED_FREE_MODELS.index(probe["model"]),
        ),
    )


def write_summary(task: str, models: list[dict[str, Any]], selected: str | None) -> None:
    target = os.environ.get("GITHUB_STEP_SUMMARY")
    if not target:
        return
    lines = [
        "### OpenCode free-model router",
        "",
        f"Task: `{task}`. Only the two audited zero-retention free models are eligible.",
        "",
        "| Candidate | Tool/response probe | Fact check | Seconds | Score |",
        "|---|---|---|---:|---:|",
    ]
    for model in models:
        lines.append(
            "| `{}` | {} | {} | {} | {} |".format(
                model["model"],
                "pass" if model.get("passed") else "fail",
                "pass" if model.get("factual") else "n/a",
                model.get("elapsed_seconds", "n/a"),
                model.get("score", 0),
            )
        )
    lines.extend(["", f"**Selected:** `{selected}`" if selected else "**No eligible model passed.**"])
    with Path(target).open("a", encoding="utf-8") as out:
        out.write("\n".join(lines) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("select", choices=["select"])
    parser.add_argument("--task", choices=TASKS, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()

    try:
        available = discover_models()
    except RuntimeError as exc:
        args.report.write_text(
            json.dumps({"task": args.task, "error": str(exc), "probes": []}), encoding="utf-8"
        )
        print(f"::error::{exc}", file=sys.stderr)
        return 1
    # Never probe other providers, non-free model IDs or newly advertised free
    # models that have not been explicitly reviewed and added to the allowlist.
    ordered = [model for model in APPROVED_FREE_MODELS if model in available]
    probes = [probe_model(model, args.task) for model in ordered]
    try:
        selected = choose_model(probes)["model"]
    except RuntimeError as exc:
        args.report.write_text(
            json.dumps({"task": args.task, "available": ordered, "probes": probes}, indent=2),
            encoding="utf-8",
        )
        write_summary(args.task, probes, None)
        print(f"::error::{exc}", file=sys.stderr)
        return 1
    args.report.write_text(
        json.dumps(
            {"task": args.task, "available": ordered, "selected": selected, "probes": probes},
            indent=2,
        ),
        encoding="utf-8",
    )
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with Path(output).open("a", encoding="utf-8") as target:
            target.write(f"model={selected}\n")
    write_summary(args.task, probes, selected)
    print(f"Selected approved free model for {args.task}: {selected}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
