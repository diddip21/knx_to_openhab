"""Validate planner responses and report only bounded, content-free diagnostics."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .scope import no_duplicates, normalize_scope

MAX_PLAN_CHARS = 16_000
MAX_EVENT_BYTES = 1_500_000
MAX_RESPONSE_CHARS = 128_000
ERROR_MESSAGES = {
    "provider_error": "OpenCode emitted an error event; no plan was accepted",
    "empty_response": "OpenCode returned no text response",
    "invalid_json": "The model response is not one valid JSON object",
    "invalid_schema": "The response must contain kind, markdown and a plan scope",
    "markdown_too_short": "The plan or questions text is shorter than 20 characters",
    "markdown_too_long": "The plan or questions text exceeds the 16000-character limit",
    "missing_scope": "New plans require a structured files/create/required scope",
    "invalid_scope": "The proposed file scope does not satisfy the repository policy",
    "output_truncated": "OpenCode reported an incomplete response",
    "output_limit": "OpenCode output exceeded the bounded capture limit",
    "cli_error": "OpenCode exited unsuccessfully",
    "cli_unavailable": "The OpenCode command could not be started",
    "timeout": "The bounded OpenCode attempt timed out",
    "budget_exhausted": "The total planner time budget was exhausted",
    "invalid_router_report": "The selected model is not approved and verified by this router run",
    "prompt_limit": "The planning prompt exceeds the safe command argument limit",
    "context_changed": "The checkout, request, policy or research evidence changed",
    "resume_unavailable": "The exact private planning session cannot be safely resumed",
    "diagnostic_incomplete": "The private replay did not prove interruption, resume and evidence reading",
}


class ModelResponseError(ValueError):
    """A fixed error code, never a provider message or model-controlled excerpt."""

    def __init__(self, code: str, **diagnostics: int | float) -> None:
        self.code = code
        self.diagnostics = diagnostics
        suffix = ", ".join(f"{key}={value}" for key, value in sorted(diagnostics.items()))
        super().__init__(f"{code}: {ERROR_MESSAGES[code]}" + (f" ({suffix})" if suffix else ""))


def inspect_events(output: str) -> tuple[str, dict[str, int]]:
    """Read the CLI envelope; an exit code of zero does not make error events valid."""
    stats = {
        "event_count": 0,
        "text_events": 0,
        "error_events": 0,
        "provider_http_status": 0,
        "invalid_event_lines": 0,
        "tool_errors": 0,
        "truncated_events": 0,
    }
    fragments = []
    for line in output.splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except ValueError:
            stats["invalid_event_lines"] += 1
            continue
        if not isinstance(event, dict):
            stats["invalid_event_lines"] += 1
            continue
        stats["event_count"] += 1
        part = event.get("part")
        part = part if isinstance(part, dict) else {}
        if event.get("type") == "error":
            stats["error_events"] += 1
            error = event.get("error")
            error = error if isinstance(error, dict) else {}
            data = error.get("data")
            data = data if isinstance(data, dict) else {}
            status = data.get(
                "statusCode", data.get("status", error.get("statusCode", error.get("status")))
            )
            if type(status) is int and 100 <= status <= 599:
                stats["provider_http_status"] = status
        elif event.get("type") == "text" and isinstance(part.get("text"), str):
            fragments.append(part["text"])
            stats["text_events"] += 1
        elif event.get("type") == "tool_use":
            state = part.get("state")
            if isinstance(state, dict) and state.get("status") == "error":
                stats["tool_errors"] += 1
        elif event.get("type") == "step_finish" and part.get("reason") in {
            "length",
            "max_tokens",
            "max_steps",
        }:
            stats["truncated_events"] += 1
    text = "\n".join(fragments)
    stats["response_chars"] = len(text)
    if stats["error_events"]:
        raise ModelResponseError("provider_error", **stats)
    if stats["truncated_events"]:
        raise ModelResponseError("output_truncated", **stats)
    if len(text) > MAX_RESPONSE_CHARS:
        raise ModelResponseError("output_limit", **stats)
    if not text.strip():
        raise ModelResponseError("empty_response", **stats)
    return text, stats


def read_events(path: Path) -> tuple[str, dict[str, int]]:
    with path.open("rb") as stream:
        output = stream.read(MAX_EVENT_BYTES + 1)
    if len(output) > MAX_EVENT_BYTES:
        raise ModelResponseError("output_limit", stdout_bytes=len(output))
    return inspect_events(output.decode("utf-8", errors="replace"))


def parse_response(text: str, *, require_scope: bool = True) -> dict[str, Any]:
    """Allow a code fence/preface, but never mine a malformed object for nested plans."""
    text = text.strip()
    if not text:
        raise ModelResponseError("empty_response")
    if len(text) > MAX_RESPONSE_CHARS:
        raise ModelResponseError("output_limit", response_chars=len(text))
    fenced = re.fullmatch(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
    if fenced:
        text = fenced.group(1).strip()
    decoder = json.JSONDecoder(object_pairs_hook=no_duplicates)
    try:
        try:
            result = json.loads(text, object_pairs_hook=no_duplicates)
        except json.JSONDecodeError:
            if text.startswith(("{", "[")):
                raise
            # A short preface is tolerated. Only its first JSON value is considered.
            start = text.index("{")
            result, end = decoder.raw_decode(text[start:])
            tail = text[start + end :].strip()
            if tail not in {"", "```"}:
                raise ValueError("Unexpected trailing response")
    except (TypeError, ValueError):
        raise ModelResponseError("invalid_json") from None
    if (
        not isinstance(result, dict)
        or set(result) - {"kind", "markdown", "scope"}
        or result.get("kind") not in ("questions", "plan")
        or not isinstance(result.get("markdown"), str)
        or (result["kind"] == "questions" and "scope" in result)
    ):
        raise ModelResponseError("invalid_schema")
    markdown = result["markdown"].strip()
    if len(markdown) < 20:
        raise ModelResponseError("markdown_too_short", characters=len(markdown), minimum=20)
    if len(markdown) > MAX_PLAN_CHARS:
        raise ModelResponseError(
            "markdown_too_long", characters=len(markdown), limit=MAX_PLAN_CHARS
        )
    response: dict[str, Any] = {"kind": result["kind"], "markdown": markdown}
    if result["kind"] == "plan":
        if "scope" not in result:
            if require_scope:
                raise ModelResponseError("missing_scope")
        else:
            try:
                response["scope"] = normalize_scope(result["scope"])
            except ValueError:
                raise ModelResponseError("invalid_scope") from None
    return response
