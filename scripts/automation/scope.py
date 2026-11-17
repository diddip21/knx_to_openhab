"""Explicit owner-approved task scope. Issue/model text never grants file access."""

from __future__ import annotations

import json
import re
from pathlib import PurePosixPath
from typing import Any

from .approval import PLAN_MARKER, authorize, text_digest

MAX_FILES = 20
MAX_FILE_BYTES = 300_000
MAX_TOTAL_BYTES = 1_250_000
MAX_CHANGED_LINES = 2500
MAX_REPAIR_FILES = 12
MAX_REPAIR_LINES = 650
MAX_REPAIRS = 2
SHA = re.compile(r"^[0-9a-f]{40}$")
BRANCH = re.compile(r"^ai/issue-([1-9][0-9]*)-plan-v([1-9][0-9]*)-run-([1-9][0-9]*)$")
COMMAND_REF = re.compile(r"<!-- ai-implementation-command: ([1-9][0-9]*) -->")
TASK_REF = re.compile(r"<!-- ai-task: (\{[^\n]*\}) -->")
SUFFIXES = {".py", ".js", ".css", ".html", ".json", ".md", ".template"}
BLOCKED_NAMES = {
    "AGENTS.md",
    "CONTRIBUTING.md",
    "conftest.py",
    "setup.py",
    "sitecustomize.py",
    "usercustomize.py",
    "opencode.json",
    "opencode.jsonc",
    "package.json",
    "package-lock.json",
    "npm-shrinkwrap.json",
    "jsconfig.json",
    "tsconfig.json",
    "pytest.ini",
    "pyproject.toml",
    "VERSION",
}


def safe_path(value: Any) -> str:
    if (
        not isinstance(value, str)
        or len(value) > 220
        or not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_./-]*", value)
    ):
        raise ValueError("Invalid task path: only literal repository-relative paths are allowed")
    path = PurePosixPath(value)
    if (
        str(path) != value
        or any(part.startswith(".") for part in path.parts)
        or path.parts[:2] in {("tests", "automation"), ("tests", "ai_pipeline")}
        or path.suffix not in SUFFIXES
        or path.name in BLOCKED_NAMES
        or (len(path.parts) > 1 and path.parts[0] not in {"web_ui", "tests", "docs"})
        or path.name.startswith(
            (
                "requirements",
                "test_ai_",
                "test_issue",
                "test_ci_repair",
                "test_opencode",
                "test_release_",
            )
        )
    ):
        raise ValueError("Task path is outside the global source policy")
    return value


def no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key in owner scope")
        result[key] = value
    return result


def normalize_scope(raw: Any) -> dict[str, list[str]]:
    if not isinstance(raw, dict) or set(raw) - {"files", "create", "required"}:
        raise ValueError("Scope supports only files, create and required")
    result: dict[str, list[str]] = {}
    for key in ("files", "create", "required"):
        paths = raw.get(key, [])
        if not isinstance(paths, list) or len(paths) > MAX_FILES:
            raise ValueError("Scope must contain bounded path lists")
        values = [safe_path(p) for p in paths]
        if len(set(values)) != len(values):
            raise ValueError("Duplicate scope paths")
        result[key] = sorted(values)
    allowed = set(result["files"])
    if (
        not allowed
        or not set(result["create"]) <= allowed
        or not set(result["required"]) <= allowed
    ):
        raise ValueError("Empty or inconsistent owner scope")
    if any(not p.endswith(".md") for p in allowed) and not any(
        p.startswith("tests/") and p.endswith(".py") for p in allowed
    ):
        raise ValueError("Code tasks must permit a Python regression test")
    return result


def scope_from_command(body: str) -> dict[str, list[str]]:
    if len(body) > 14000:
        raise ValueError("Implementation command too large")
    parts = body.strip().split("\n", 1)
    if len(parts) != 2:
        raise ValueError("Explicit owner file scope is missing; no implicit pilot permissions")
    payload = parts[1].strip()
    fenced = re.fullmatch(r"```json\s*\n([\s\S]*)\n```", payload)
    if fenced:
        payload = fenced.group(1)
    return normalize_scope(json.loads(payload, object_pairs_hook=no_duplicates))


def plan_scope(body: str) -> dict[str, list[str]]:
    """Read a proposal, never an authorization, from the immutable bot plan."""
    match = PLAN_MARKER.match(body)
    if not match:
        raise ValueError("No structured plan scope; use the full /ai implement command with JSON")
    state = json.loads(match.group(1), object_pairs_hook=no_duplicates)
    if "scope" not in state:
        raise ValueError("No structured plan scope; use the full /ai implement command with JSON")
    return normalize_scope(state["scope"])


def authorize_task(
    issue: dict[str, Any],
    comments: list[dict[str, Any]],
    command: dict[str, Any],
    actor: str,
    owner: str,
    *,
    expected_issue_number: int,
) -> dict[str, Any]:
    context = authorize(
        issue, comments, command, actor, owner, expected_issue_number=expected_issue_number
    )
    body = str(command.get("body") or "").strip()
    if re.fullmatch(r"/ai start v[1-9][0-9]*", body, re.IGNORECASE):
        scope = plan_scope(context["plan"])
    else:
        if body.lower().startswith("/ai start "):
            raise ValueError("Use only /ai start vN; changing scope requires a new reviewed plan")
        scope = scope_from_command(body)
    context["scope"] = scope
    context["scope_sha256"] = text_digest(json.dumps(scope, sort_keys=True, separators=(",", ":")))
    return context


def validate_paths(paths: list[str], scope: dict[str, list[str]], *, repair: bool) -> list[str]:
    maximum = MAX_REPAIR_FILES if repair else MAX_FILES
    if not paths or len(paths) > maximum or len(paths) != len(set(paths)):
        raise ValueError("No changes, too many files or duplicate paths")
    if not set(paths) <= set(scope["files"]):
        raise ValueError("Changed files are outside the owner-approved allowlist")
    for path in paths:
        safe_path(path)
    if not repair:
        if not set(scope["required"]) <= set(paths):
            raise ValueError("Required implementation files are missing")
        if any(not p.endswith(".md") for p in paths) and not any(
            p.startswith("tests/") and p.endswith(".py") for p in paths
        ):
            raise ValueError("A changed regression test is mandatory for code changes")
    return sorted(paths)


def task_reference(context: dict[str, Any]) -> dict[str, Any]:
    return {
        key: context[key]
        for key in (
            "issue_number",
            "version",
            "command_comment_id",
            "command_sha256",
            "plan_sha256",
            "scope_sha256",
            "base_commit_sha",
        )
    }
