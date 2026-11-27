#!/usr/bin/env python3
"""Bounded planner attempts using only models verified by this run's free-model router."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import issue_bot  # noqa: E402
from automation.model_response import (  # noqa: E402
    MAX_EVENT_BYTES,
    ModelResponseError,
    inspect_events,
    parse_response,
)
from opencode_model_router import (  # noqa: E402
    APPROVED_FREE_MODELS,
    RouterError,
    discover_models,
    isolated_environment,
    probe_model,
)

TOTAL_SECONDS = 660
ATTEMPT_SECONDS = 300
REFRESH_DISCOVERY_SECONDS = 15
REFRESH_PROBE_SECONDS = 30
PROGRESS_SECONDS = 60
MAX_STDERR_BYTES = 64_000
MAX_PROMPT_BYTES = 110_000
FORMAT_ERRORS = {
    "empty_response",
    "invalid_json",
    "invalid_schema",
    "markdown_too_short",
    "markdown_too_long",
    "missing_scope",
    "invalid_scope",
}


def verified_models(model: str, report: dict[str, Any]) -> list[str]:
    if (
        model not in APPROVED_FREE_MODELS
        or not isinstance(report, dict)
        or report.get("selected") != model
    ):
        raise ModelResponseError("invalid_router_report")
    probes = report.get("probes")
    if not isinstance(probes, list):
        raise ModelResponseError("invalid_router_report")
    passed = {
        probe.get("model")
        for probe in probes
        if isinstance(probe, dict)
        and probe.get("passed") is True
        and probe.get("model") in APPROVED_FREE_MODELS
    }
    if model not in passed:
        raise ModelResponseError("invalid_router_report")
    return [model] + [other for other in APPROVED_FREE_MODELS if other != model and other in passed]


def refresh_alternate(model: str, remaining: float) -> str | None:
    """Only re-discover and probe an allowlisted alternate if a full retry fits."""
    if remaining < ATTEMPT_SECONDS + REFRESH_DISCOVERY_SECONDS + REFRESH_PROBE_SECONDS:
        return None
    try:
        available = discover_models(timeout=REFRESH_DISCOVERY_SECONDS, max_attempts=1)
    except RouterError as error:
        print(f"Planner model refresh: {error.code}", flush=True)
        return None
    for alternate in APPROVED_FREE_MODELS:
        if alternate != model and alternate in available:
            probe = probe_model(alternate, "plan", timeout=REFRESH_PROBE_SECONDS)
            if probe.get("passed") is True:
                print(f"Planner model refresh: verified {alternate}", flush=True)
                return alternate
    print("Planner model refresh: no verified alternate", flush=True)
    return None


def corrected_prompt(prompt: str, code: str) -> str:
    return (
        prompt
        + "\n\nKORREKTURHINWEIS DES CONTROLLERS: Der vorherige Versuch wurde mit "
        + code
        + " abgelehnt. Erzeuge einen neuen, kompakten Vorschlag als EIN JSON-Objekt "
        'mit "kind" (plan/questions) und "markdown". Der Markdown-Text muss 20 bis '
        "16000 Zeichen lang sein; bleibe unter 12000 Zeichen. Bei kind=plan ist ein "
        'gültiger "scope" mit files/create/required zwingend; verwende nur erlaubte '
        "exakte Pfade. Bei questions keinen scope ausgeben. Keine Einleitung, keinen "
        "Codezaun, keine zusätzlichen JSON-Felder. Ändere keine Dateien oder Berechtigungen."
    )


def execute(model: str, prompt: str, timeout: float) -> tuple[str, dict[str, Any]]:
    """Capture to private temp files, killing runaway output before reading bounded bytes."""
    command = [
        "opencode",
        "run",
        "--standalone",
        "--archived",
        "--format",
        "json",
        "--agent",
        "issue-planner",
        "--model",
        model,
        prompt,
    ]
    started = time.monotonic()
    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        try:
            process = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=stdout,
                stderr=stderr,
                env=isolated_environment(),
                start_new_session=True,
            )
        except OSError:
            return "", {"code": "cli_unavailable", "exit_code": None, "elapsed_seconds": 0}
        code = None
        next_progress = PROGRESS_SECONDS
        while process.poll() is None:
            if time.monotonic() - started >= timeout:
                code = "timeout"
                break
            if (
                os.fstat(stdout.fileno()).st_size > MAX_EVENT_BYTES
                or os.fstat(stderr.fileno()).st_size > MAX_STDERR_BYTES
            ):
                code = "output_limit"
                break
            elapsed = time.monotonic() - started
            if elapsed >= next_progress:
                print(
                    f"Planner progress: seconds={int(elapsed)}, "
                    f"stdout_bytes={os.fstat(stdout.fileno()).st_size}, "
                    f"stderr_bytes={os.fstat(stderr.fileno()).st_size}",
                    flush=True,
                )
                next_progress += PROGRESS_SECONDS
            time.sleep(0.05)
        if code:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait(timeout=5)
        stdout_bytes = os.fstat(stdout.fileno()).st_size
        stderr_bytes = os.fstat(stderr.fileno()).st_size
        if stdout_bytes > MAX_EVENT_BYTES or stderr_bytes > MAX_STDERR_BYTES:
            code = "output_limit"
        stdout.seek(0)
        output = stdout.read(MAX_EVENT_BYTES).decode("utf-8", errors="replace")
        return output, {
            "code": code,
            "exit_code": process.returncode,
            "elapsed_seconds": round(time.monotonic() - started, 2),
            "stdout_bytes": stdout_bytes,
            "stderr_bytes": stderr_bytes,
        }


def write_diagnostics(temp: Path, report: dict[str, Any]) -> None:
    # This explicit file is the only uploaded artifact; never include raw responses,
    # tool output, stderr, prompts, environment variables or provider error messages.
    (temp / "planner-diagnostics.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        lines = [
            "### AI planner response validation",
            "",
            "Only model IDs, fixed error codes, counts and timings are retained.",
            "",
            "| Attempt | Model | Result | Seconds |",
            "|---|---|---|---:|",
        ]
        for attempt in report["attempts"]:
            lines.append(
                f"| {attempt['attempt']} ({attempt['phase']}) | `{attempt['model']}` | "
                f"`{attempt['code']}` | {attempt.get('elapsed_seconds', 0)} |"
            )
        lines.extend(["", f"Result: **{report['status']}**."])
        if report.get("failure_code"):
            lines.append(f"Failure code: `{report['failure_code']}`.")
        with Path(summary).open("a", encoding="utf-8") as target:
            target.write("\n".join(lines) + "\n")


def run_plan(temp: Path, model: str, router: dict[str, Any]) -> dict[str, Any]:
    report: dict[str, Any] = {"schema_version": 1, "status": "failure", "attempts": []}
    started = time.monotonic()
    (temp / "issue-result.json").unlink(missing_ok=True)
    try:
        models = verified_models(model, router)
        prompt = (temp / "issue-prompt.txt").read_text(encoding="utf-8")
        if len(corrected_prompt(prompt, "invalid_json").encode("utf-8")) > MAX_PROMPT_BYTES:
            raise ModelResponseError("prompt_limit")
        phase = "initial"
        attempt_model = models[0]
        attempt_prompt = prompt
        while len(report["attempts"]) < 3:
            remaining = TOTAL_SECONDS - (time.monotonic() - started)
            if remaining <= 0:
                raise ModelResponseError("budget_exhausted")
            timeout = min(ATTEMPT_SECONDS, remaining)
            print(
                f"Planner attempt {len(report['attempts']) + 1}: "
                f"phase={phase}, model={attempt_model}, timeout={timeout:.1f}s",
                flush=True,
            )
            output, metrics = execute(attempt_model, attempt_prompt, timeout)
            attempt = {
                "attempt": len(report["attempts"]) + 1,
                "model": attempt_model,
                "phase": phase,
                **metrics,
            }
            report["attempts"].append(attempt)
            try:
                if metrics.get("code"):
                    raise ModelResponseError(metrics["code"])
                # Check error events even when the CLI exits zero, before considering text.
                try:
                    text, event_metrics = inspect_events(output)
                except ModelResponseError as event_error:
                    if event_error.code != "provider_error" and metrics["exit_code"] != 0:
                        raise ModelResponseError("cli_error", **event_error.diagnostics) from None
                    raise
                attempt.update(event_metrics)
                if metrics["exit_code"] != 0:
                    raise ModelResponseError("cli_error")
                response = parse_response(text)
                attempt["markdown_chars"] = len(response["markdown"])
            except ModelResponseError as error:
                attempt["code"] = error.code
                attempt.update(error.diagnostics)
                if phase == "initial" and error.code in FORMAT_ERRORS:
                    phase = "format_retry"
                    attempt_prompt = corrected_prompt(prompt, error.code)
                elif phase != "fallback" and len(models) > 1:
                    phase = "fallback"
                    attempt_model = models[1]
                    attempt_prompt = corrected_prompt(prompt, error.code)
                elif error.code == "timeout" and phase in {"initial", "format_retry"}:
                    # The first verified model can time out on a real plan despite
                    # passing the short probe. Reserve time for a full fresh attempt.
                    remaining = TOTAL_SECONDS - (time.monotonic() - started)
                    alternate = refresh_alternate(attempt_model, remaining)
                    if alternate is not None:
                        phase = "fallback"
                        attempt_model = alternate
                    else:
                        phase = "timeout_retry"
                    attempt_prompt = corrected_prompt(prompt, error.code)
                else:
                    raise
                continue
            attempt["code"] = "valid_response"
            # finish independently revalidates the envelope, schema and scope before writing.
            (temp / "opencode-events.jsonl").write_text(output, encoding="utf-8")
            issue_bot.finish(temp)
            report["status"] = "success"
            return report
        raise ModelResponseError("budget_exhausted")
    except ModelResponseError as error:
        report["failure_code"] = error.code
        raise
    finally:
        report["elapsed_seconds"] = round(time.monotonic() - started, 2)
        write_diagnostics(temp, report)


def main() -> int:
    temp = Path(os.environ["RUNNER_TEMP"])
    router = json.loads((temp / "model-router.json").read_text(encoding="utf-8"))
    try:
        run_plan(temp, os.environ.get("MODEL", ""), router)
    except ModelResponseError as error:
        print(f"::error::AI planner stopped: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
