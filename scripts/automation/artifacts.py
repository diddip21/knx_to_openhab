"""Bounded text artifacts with independent validation in the publisher checkout."""

from __future__ import annotations

import base64
import difflib
import hashlib
import json
import os
import stat
import subprocess
from pathlib import Path
from typing import Any

from .git_helpers import git
from .scope import (
    MAX_CHANGED_LINES,
    MAX_FILE_BYTES,
    MAX_REPAIR_LINES,
    MAX_TOTAL_BYTES,
    safe_path,
    validate_paths,
)


def load_json(path: Path) -> Any:
    if path.is_symlink() or path.stat().st_size > 4_000_000:
        raise ValueError("Unsafe or oversized JSON artifact")
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def base_file(root: Path, path: str) -> tuple[str | None, bytes]:
    safe_path(path)
    entry = git("ls-tree", "HEAD", "--", path, cwd=root)
    if not entry:
        return None, b""
    metadata, actual_path = entry.split("\t", 1)
    mode, kind, blob = metadata.split()
    if actual_path != path or kind != "blob" or mode not in {"100644", "100755"}:
        raise ValueError("Only regular tracked files may be changed")
    data = subprocess.run(
        ["git", "cat-file", "blob", blob], cwd=root, capture_output=True, check=True
    ).stdout
    if len(data) > MAX_FILE_BYTES:
        raise ValueError("Original file exceeds task size limit")
    data.decode("utf-8")
    return mode, data


def file_bytes(root: Path, path: str) -> bytes:
    safe_path(path)
    target = root
    for part in path.split("/"):
        target = target / part
        if target.is_symlink():
            raise ValueError("Symlink in candidate path")
    info = target.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise ValueError("Candidate must be a regular, non-hardlinked file")
    if not 1 <= info.st_size <= MAX_FILE_BYTES:
        raise ValueError("File size outside allowed range")
    data = target.read_bytes()
    data.decode("utf-8")
    if b"\0" in data:
        raise ValueError("Binary candidate is forbidden")
    return data


def changed_paths(root: Path) -> list[str]:
    changed = git(
        "diff",
        "--no-ext-diff",
        "--no-textconv",
        "--name-only",
        "--diff-filter=ACM",
        "HEAD",
        cwd=root,
    ).splitlines()
    illegal = git(
        "diff",
        "--no-ext-diff",
        "--no-textconv",
        "--name-only",
        "--diff-filter=DRT",
        "HEAD",
        cwd=root,
    ).splitlines()
    if illegal:
        raise ValueError("Deletion, rename and type changes are forbidden")
    added = git("ls-files", "--others", "--exclude-standard", cwd=root).splitlines()
    git("diff", "--no-ext-diff", "--no-textconv", "--check", "HEAD", cwd=root)
    return changed + added


def validate_files(
    records: Any,
    context: dict[str, Any],
    root: Path,
    *,
    repair: bool,
) -> list[dict[str, str]]:
    if not isinstance(records, list) or any(not isinstance(r, dict) for r in records):
        raise ValueError("Expected candidate file objects")
    if any(set(r) != {"path", "content_b64", "sha256"} for r in records):
        raise ValueError("Unexpected candidate file fields")
    paths = [r["path"] for r in records]
    if any(not isinstance(p, str) for p in paths):
        raise ValueError("File paths must be strings")
    validate_paths(paths, context["scope"], repair=repair)
    total = changed_lines = 0
    verified = []
    for record in records:
        encoded = record["content_b64"]
        if not isinstance(encoded, str) or len(encoded) > MAX_FILE_BYTES * 2:
            raise ValueError("Oversized or invalid base64 candidate")
        try:
            data = base64.b64decode(encoded, validate=True)
            text = data.decode("utf-8")
        except (ValueError, UnicodeError) as exc:
            raise ValueError("Invalid UTF-8/base64 candidate") from exc
        total += len(data)
        if not 1 <= len(data) <= MAX_FILE_BYTES or total > MAX_TOTAL_BYTES or "\0" in text:
            raise ValueError("Candidate size or encoding outside limits")
        if hashlib.sha256(data).hexdigest() != record["sha256"]:
            raise ValueError("Candidate digest mismatch")
        mode, old = base_file(root, record["path"])
        if mode is None and (repair or record["path"] not in context["scope"]["create"]):
            raise ValueError("New file not explicitly approved, or new file during repair")
        if data == old:
            raise ValueError("No-op file in candidate artifact")
        for line in difflib.unified_diff(old.decode("utf-8").splitlines(), text.splitlines(), n=0):
            if line.startswith(("+++", "---")):
                continue
            if line.startswith(("+", "-")):
                changed_lines += 1
            if line.startswith("+"):
                added = line[1:]
                if added.rstrip(" \t") != added or added.startswith(("<<<<<<< ", ">>>>>>> ")):
                    raise ValueError("Whitespace error or unresolved conflict in candidate")
        verified.append({**record, "mode": mode or "100644"})
    if changed_lines > (MAX_REPAIR_LINES if repair else MAX_CHANGED_LINES):
        raise ValueError("Candidate diff is too large")
    return verified


def collect(context: dict[str, Any], root: Path, *, repair: bool) -> dict[str, Any]:
    if git("rev-parse", "HEAD", cwd=root) != context["base_commit_sha"]:
        raise ValueError("Candidate HEAD changed during generation")
    paths = validate_paths(changed_paths(root), context["scope"], repair=repair)
    records = []
    for path in paths:
        data = file_bytes(root, path)
        records.append(
            {
                "path": path,
                "content_b64": base64.b64encode(data).decode("ascii"),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        )
    validate_files(records, context, root, repair=repair)
    return {**{key: value for key, value in context.items() if key != "plan"}, "files": records}


def recheck(
    candidate: dict[str, Any],
    fresh: dict[str, Any],
    root: Path,
    *,
    repair: bool,
) -> dict[str, Any]:
    expected = {key: value for key, value in fresh.items() if key != "plan"}
    if set(candidate) != set(expected) | {"files"}:
        raise ValueError("Unexpected artifact metadata")
    for key, value in expected.items():
        if candidate.get(key) != value:
            raise ValueError(f"Stale or forged candidate metadata: {key}")
    files = validate_files(candidate["files"], fresh, root, repair=repair)
    return {**expected, "files": files}


def write_agent(
    root: Path, context: dict[str, Any], trusted_template: Path, *, repair: bool
) -> None:
    """Generate literal file permissions; the model cannot choose or broaden them."""
    text = trusted_template.read_text(encoding="utf-8")
    body = text.split("---", 2)[-1].strip()
    permissions = [
        {"action": "*", "resource": "*", "effect": "deny"},
        *[
            {"action": action, "resource": "*", "effect": "allow"}
            for action in ("read", "glob", "grep", "skill")
        ],
    ]
    for path in context["scope"]["files"]:
        mode, _ = base_file(root, path)
        if mode is None:
            if repair:
                continue
            if path not in context["scope"]["create"]:
                raise ValueError("Missing file is not approved for creation")
        # Exact relative and absolute names, never suffix globs such as */foo.py.
        for resource in (path, str((root / path).resolve())):
            permissions.append({"action": "edit", "resource": resource, "effect": "allow"})
    header = {
        "description": "Explicitly owner-scoped implementation or repair",
        "mode": "primary",
        "steps": 120,
        "permissions": permissions,
    }
    target = root / ".opencode/agents/ai-task.md"
    if target.is_symlink() or not target.parent.is_dir():
        raise ValueError("Trusted agent path missing or unsafe")
    # JSON is a YAML subset and avoids a new runtime YAML dependency.
    target.write_text(
        "---\n" + json.dumps(header, indent=2) + "\n---\n\n" + body + "\n", encoding="utf-8"
    )


def runtime_dir() -> Path:
    destination = Path(os.environ.get("RUNNER_TEMP", "/tmp"))
    destination.mkdir(parents=True, exist_ok=True)
    return destination
