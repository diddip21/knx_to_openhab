#!/usr/bin/env python3
"""Bounded generation with private completeness feedback and safe diagnostics.

This runner does not publish or authorize a candidate. The existing trusted
format, collect and publisher checks must still run after a successful result.
A normally finished, safe but incomplete implementation gets one targeted
completion with the same verified model. Other retryable failures may use one
different model verified by this router, after a literal scoped rollback.
Both paths share the existing two-call and total-time limits.
"""

from __future__ import annotations

import ctypes
import difflib
import hashlib
import json
import os
import selectors
import signal
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

# python -I must import controllers from this trusted checkout, never candidate.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from automation import artifacts  # noqa: E402
from automation.provider_policy import classify, fallback_model, permits_fallback  # noqa: E402
from automation.scope import (  # noqa: E402
    MAX_CHANGED_LINES,
    MAX_FILE_BYTES,
    MAX_FILES,
    MAX_REPAIR_FILES,
    MAX_REPAIR_LINES,
    MAX_REPAIRS,
    MAX_TOTAL_BYTES,
    SHA,
    no_duplicates,
    normalize_scope,
)
from opencode_model_router import (  # noqa: E402
    ALL_APPROVED_MODELS,
    isolated_environment,
    rank_models,
)

MODE_LIMITS = {"implement": (1150.0, 1800.0), "repair": (750.0, 1000.0)}
MAX_STDOUT_BYTES = 8_000_000
MAX_STDERR_BYTES = 64_000
MAX_LINE_BYTES = 1_500_000
MAX_EVENTS = 10_000
MAX_PROMPT_BYTES = 400_000
MAX_TREE_FILES = 30_000
MAX_TREE_BYTES = 300_000_000
PROGRESS_SECONDS = 30.0
POLL_SECONDS = 0.05
PR_SET_CHILD_SUBREAPER = 36
PR_GET_CHILD_SUBREAPER = 37
AGENT_PATH = ".opencode/agents/ai-task.md"
INPUT_NAMES = ("task-context.json", "task-prompt.txt", "model.json")
EVENT_NAMES = ("step_start", "step_finish", "text", "reasoning", "tool_use", "error", "other")
TOOL_NAMES = ("read", "glob", "grep", "skill", "edit", "write", "patch", "apply_patch", "other")
SKILL_NAMES = (
    "using-superpowers",
    "brainstorming",
    "writing-plans",
    "executing-plans",
    "test-driven-development",
    "systematic-debugging",
    "verification-before-completion",
    "requesting-code-review",
    "receiving-code-review",
    "finishing-a-development-branch",
    "using-git-worktrees",
    "dispatching-parallel-agents",
    "subagent-driven-development",
    "other",
)
RETRYABLE = {
    "timeout",
    "cli_error",
    "provider_error",
    "invalid_events",
    "empty_response",
    "output_truncated",
    "output_limit",
    "tool_error",
    "incomplete_tools",
    "no_changes",
    "required_missing",
    "regression_missing",
    "empty_candidate_file",
}
ERROR_CODES = RETRYABLE | {
    "invalid_mode",
    "invalid_context",
    "invalid_router_report",
    "unsafe_input",
    "prompt_limit",
    "cli_unavailable",
    "budget_exhausted",
    "interrupted",
    "controller_error",
    "process_cleanup",
    "head_changed",
    "git_metadata_changed",
    "agent_changed",
    "input_changed",
    "foreign_path_changed",
    "unsafe_file",
    "file_deleted",
    "file_mode_changed",
    "new_file_forbidden",
    "candidate_limit",
    "tool_policy",
    "initial_changes",
    "rollback_failed",
    "diagnostics_unavailable",
}
INTERRUPTED = False


class GenerationError(ValueError):
    """The message is a controller-owned enum, never untrusted diagnostic text."""

    def __init__(self, code: str) -> None:
        self.code = code if code in ERROR_CODES else "controller_error"
        super().__init__(self.code)


def _read_regular(path: Path, limit: int) -> bytes:
    """Do not follow a final symlink or retain unbounded external input."""
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > limit:
        raise GenerationError("unsafe_file")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        actual = os.fstat(fd)
        if (actual.st_dev, actual.st_ino, actual.st_nlink) != (info.st_dev, info.st_ino, 1):
            raise GenerationError("unsafe_file")
        with os.fdopen(fd, "rb", closefd=False) as stream:
            data = stream.read(limit + 1)
        if len(data) > limit:
            raise GenerationError("candidate_limit")
        return data
    finally:
        os.close(fd)


def _git(root: Path, *args: str) -> bytes:
    environment = isolated_environment()
    environment.update(
        GIT_OPTIONAL_LOCKS="0", GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull
    )
    return subprocess.run(
        [
            "git",
            "--no-replace-objects",
            "--literal-pathspecs",
            "-c",
            "core.hooksPath=/dev/null",
            "-c",
            "core.fsmonitor=false",
            "-c",
            "core.untrackedCache=false",
            *args,
        ],
        cwd=root,
        env=environment,
        capture_output=True,
        check=True,
        timeout=15,
    ).stdout


def _manifest(root: Path, *, git_metadata: bool = False) -> dict[str, tuple[Any, ...]]:
    """Include ignored/untracked paths; a .gitignore edit cannot hide a mutation."""
    result: dict[str, tuple[Any, ...]] = {}
    total = 0

    def visit(folder: Path) -> None:
        nonlocal total
        for child in sorted(folder.iterdir()):
            relative = child.relative_to(root).as_posix()
            if (not git_metadata and relative == ".git") or (git_metadata and relative == "index"):
                continue
            if len(result) >= MAX_TREE_FILES:
                raise GenerationError("candidate_limit")
            info = child.lstat()
            mode = stat.S_IMODE(info.st_mode)
            if stat.S_ISLNK(info.st_mode):
                result[relative] = ("link", mode, os.readlink(child))
            elif stat.S_ISDIR(info.st_mode):
                result[relative] = ("dir", mode)
                visit(child)
            elif stat.S_ISREG(info.st_mode):
                total += info.st_size
                if total > MAX_TREE_BYTES:
                    raise GenerationError("candidate_limit")
                data = _read_regular(child, MAX_TREE_BYTES)
                result[relative] = ("file", mode, len(data), hashlib.sha256(data).hexdigest())
            else:
                raise GenerationError("unsafe_file")

    visit(root)
    return result


def verified_models(
    model: str, report: Any, task: str = "implement"
) -> tuple[list[str], list[dict[str, Any]]]:
    if (
        model not in ALL_APPROVED_MODELS
        or not isinstance(report, dict)
        or report.get("task") != task
        or report.get("selected") != model
        or not isinstance(report.get("probes"), list)
    ):
        raise GenerationError("invalid_router_report")
    probes: dict[str, bool] = {}
    for probe in report["probes"]:
        if not isinstance(probe, dict) or probe.get("model") not in ALL_APPROVED_MODELS:
            continue
        name = probe["model"]
        if name in probes or type(probe.get("passed")) is not bool:
            raise GenerationError("invalid_router_report")
        probes[name] = probe["passed"]
    if not probes.get(model):
        raise GenerationError("invalid_router_report")
    models = [model] + [p["model"] for p in rank_models(report["probes"]) if p["model"] != model]
    return models, [{"model": m, "passed": probes[m]} for m in ALL_APPROVED_MODELS if m in probes]


class CandidateBoundary:
    """Remember original bytes and refuse to conceal any out-of-scope mutation."""

    def __init__(self, root: Path, temp: Path, context: dict[str, Any], mode: str) -> None:
        self.root, self.temp, self.context, self.mode = root, temp, context, mode
        self.scope = normalize_scope(context.get("scope"))
        if context.get("mode") != mode or not SHA.fullmatch(str(context.get("base_commit_sha"))):
            raise GenerationError("invalid_context")
        if mode == "repair" and (
            type(context.get("attempt")) is not int or not 1 <= context["attempt"] <= MAX_REPAIRS
        ):
            raise GenerationError("invalid_context")
        self.head = context["base_commit_sha"]
        if _git(root, "rev-parse", "HEAD").decode().strip() != self.head:
            raise GenerationError("head_changed")
        changes = set(
            _git(root, "diff", "--no-ext-diff", "--no-textconv", "--name-only", "-z", "HEAD")
            .decode()
            .split("\0")
        ) - {""}
        if changes - {AGENT_PATH} or _git(root, "ls-files", "--others", "--exclude-standard", "-z"):
            raise GenerationError("initial_changes")
        self.gitdir = Path(_git(root, "rev-parse", "--absolute-git-dir").decode().strip())
        self.git_pointer = _read_regular(root / ".git", 4096) if (root / ".git").is_file() else None
        self.git_manifest = _manifest(self.gitdir, git_metadata=True)
        _read_regular(self.gitdir / "index", MAX_TREE_BYTES)
        self.index = _git(root, "ls-files", "--stage", "-z")
        self.inputs = {name: _read_regular(temp / name, 4_000_000) for name in INPUT_NAMES}
        self.agent = _read_regular(root / AGENT_PATH, MAX_FILE_BYTES)
        if not self.agent:
            raise GenerationError("agent_changed")
        self.tree = _manifest(root)
        self.originals: dict[str, tuple[str | None, bytes]] = {}
        self.allowed_directories: set[str] = set()
        for path in self.scope["files"]:
            for parent in Path(path).parents:
                if str(parent) != ".":
                    self.allowed_directories.add(parent.as_posix())
                    existing = self.tree.get(parent.as_posix())
                    if existing and existing[0] != "dir":
                        raise GenerationError("unsafe_file")
            original = artifacts.base_file(root, path)
            self.originals[path] = original
            if original[0] is None:
                if path in self.tree or (mode != "repair" and path not in self.scope["create"]):
                    raise GenerationError("new_file_forbidden")
            elif _read_regular(root / path, MAX_FILE_BYTES) != original[1]:
                raise GenerationError("initial_changes")

    def inspect(self) -> tuple[list[str], dict[str, int]]:
        """Called only once the CLI and its detached descendants have stopped."""
        if self.git_pointer is None:
            if (self.root / ".git").is_symlink() or not (self.root / ".git").is_dir():
                raise GenerationError("git_metadata_changed")
        elif _read_regular(self.root / ".git", 4096) != self.git_pointer:
            raise GenerationError("git_metadata_changed")
        current_git = _manifest(self.gitdir, git_metadata=True)
        if current_git != self.git_manifest:
            # HEAD has its own useful fixed code; no Git config is evaluated here.
            if current_git.get("HEAD") != self.git_manifest.get("HEAD"):
                raise GenerationError("head_changed")
            raise GenerationError("git_metadata_changed")
        if _git(self.root, "rev-parse", "HEAD").decode().strip() != self.head:
            raise GenerationError("head_changed")
        _read_regular(self.gitdir / "index", MAX_TREE_BYTES)
        if _git(self.root, "ls-files", "--stage", "-z") != self.index:
            raise GenerationError("git_metadata_changed")
        if any(
            _read_regular(self.temp / name, 4_000_000) != data for name, data in self.inputs.items()
        ):
            raise GenerationError("input_changed")
        if _read_regular(self.root / AGENT_PATH, MAX_FILE_BYTES) != self.agent:
            raise GenerationError("agent_changed")
        current = _manifest(self.root)
        for path in current.keys() | self.tree.keys():
            if path in self.originals:
                continue
            if (
                path not in self.tree
                and path in self.allowed_directories
                and current[path][0] == "dir"
            ):
                continue
            if current.get(path) != self.tree.get(path):
                raise GenerationError(
                    "agent_changed" if path == AGENT_PATH else "foreign_path_changed"
                )
        changed, total, lines = [], 0, 0
        maximum = MAX_REPAIR_FILES if self.mode == "repair" else MAX_FILES
        line_limit = MAX_REPAIR_LINES if self.mode == "repair" else MAX_CHANGED_LINES
        for path, (mode, original) in self.originals.items():
            entry = current.get(path)
            if entry is None:
                if mode is not None:
                    raise GenerationError("file_deleted")
                continue
            if entry[0] != "file":
                raise GenerationError("unsafe_file")
            if mode is None and (self.mode == "repair" or path not in self.scope["create"]):
                raise GenerationError("new_file_forbidden")
            expected_mode = int(mode[-3:], 8) if mode else 0o644
            if entry[1] != expected_mode:
                raise GenerationError("file_mode_changed")
            data = _read_regular(self.root / path, MAX_FILE_BYTES)
            try:
                new_text = data.decode("utf-8")
            except UnicodeError:
                raise GenerationError("unsafe_file") from None
            if "\0" in new_text:
                raise GenerationError("unsafe_file")
            if data == original and mode is not None:
                continue
            changed.append(path)
            total += len(data)
            old_lines, new_lines = original.decode("utf-8").splitlines(), new_text.splitlines()
            if (
                len(changed) > maximum
                or total > MAX_TOTAL_BYTES
                or lines + abs(len(new_lines) - len(old_lines)) > line_limit
            ):
                raise GenerationError("candidate_limit")
            matcher = difflib.SequenceMatcher(None, old_lines, new_lines)
            lines += sum(
                i2 - i1 + j2 - j1 for tag, i1, i2, j1, j2 in matcher.get_opcodes() if tag != "equal"
            )
        if len(changed) > maximum or lines > line_limit or total > MAX_TOTAL_BYTES:
            raise GenerationError("candidate_limit")
        return changed, {
            "changed_files": len(changed),
            "changed_lines": lines,
            "changed_bytes": total,
            "required_files": len(self.scope["required"]),
            "required_files_changed": len(set(changed) & set(self.scope["required"])),
        }

    def completeness(self, changed: list[str]) -> str | None:
        if not changed:
            return "no_changes"
        if any((self.root / path).stat().st_size == 0 for path in changed):
            return "empty_candidate_file"
        if self.mode == "implement":
            if not set(self.scope["required"]) <= set(changed):
                return "required_missing"
            if any(not p.endswith(".md") for p in changed) and not any(
                p.startswith("tests/") and p.endswith(".py") for p in changed
            ):
                return "regression_missing"
        return None

    def rollback(self) -> None:
        changed, _ = self.inspect()
        for path in changed:
            mode, original = self.originals[path]
            target = self.root / path
            if mode is None:
                target.unlink()
            else:
                # No blanket clean/reset: only exact approved regular files.
                fd = os.open(target, os.O_WRONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
                try:
                    current = os.fstat(fd)
                    if not stat.S_ISREG(current.st_mode) or current.st_nlink != 1:
                        raise GenerationError("unsafe_file")
                    os.ftruncate(fd, 0)
                    with os.fdopen(fd, "wb", closefd=False) as stream:
                        stream.write(original)
                finally:
                    os.close(fd)
        for path in sorted(
            self.allowed_directories - self.tree.keys(), key=lambda p: p.count("/"), reverse=True
        ):
            target = self.root / path
            if target.is_dir():
                target.rmdir()
        remaining, _ = self.inspect()
        if remaining:
            raise GenerationError("rollback_failed")


class EventMetrics:
    """Parse JSONL in memory, retaining fixed counters and no model text."""

    def __init__(self, root: Path, scope: dict[str, list[str]]) -> None:
        self.root, self.scope = root, scope
        self.pending: set[str] = set()
        self.buffer = bytearray()
        self.code: str | None = None
        self.last_finish: str | None = None
        self.has_text = False
        self.last_text_event = 0
        self.last_tool_error_event = 0
        self.values: dict[str, Any] = {
            "events": dict.fromkeys(EVENT_NAMES, 0),
            "tools": dict.fromkeys(TOOL_NAMES, 0),
            "skills": dict.fromkeys(SKILL_NAMES, 0),
            "event_count": 0,
            "invalid_event_lines": 0,
            "text_characters": 0,
            "tool_errors": 0,
            "pending_tools": 0,
            "provider_http_status": 0,
            "provider_failure": "none",
            "terminal_finish_seen": False,
        }

    def reject(self, code: str) -> None:
        # Later provider/text events cannot conceal an attempted policy breach.
        precedence = {
            "output_truncated": 1,
            "provider_error": 2,
            "output_limit": 3,
            "tool_policy": 4,
        }
        if self.code is None or precedence.get(code, 0) > precedence.get(self.code, 0):
            self.code = code

    def feed(self, data: bytes) -> None:
        self.buffer.extend(data)
        while b"\n" in self.buffer:
            line, _, remainder = self.buffer.partition(b"\n")
            self.buffer = bytearray(remainder)
            self.line(bytes(line))
        if len(self.buffer) > MAX_LINE_BYTES:
            self.reject("output_limit")
            self.buffer.clear()

    def line(self, line: bytes) -> None:
        if not line.strip():
            return
        if len(line) > MAX_LINE_BYTES or self.values["event_count"] >= MAX_EVENTS:
            self.reject("output_limit")
            return
        try:
            event = json.loads(line.decode("utf-8"), object_pairs_hook=no_duplicates)
            if not isinstance(event, dict) or not isinstance(event.get("type"), str):
                raise ValueError
        except (ValueError, UnicodeError, RecursionError):
            self.values["invalid_event_lines"] += 1
            return
        kind = event["type"]
        bucket = kind if kind in EVENT_NAMES else "other"
        self.values["event_count"] += 1
        self.values["events"][bucket] += 1
        part = event.get("part")
        part = part if isinstance(part, dict) else {}
        if kind in {"permission", "question", "permission_request"}:
            self.reject("tool_policy")
        elif kind == "step_start":
            # V2 can project this step's final text without token metadata or
            # step_finish. Do not inherit an earlier step's finish or text.
            self.last_finish = None
            self.has_text = False
            self.values["terminal_finish_seen"] = False
        elif kind == "error":
            policy = classify(event.get("error"))
            error = event.get("error")
            error = error if isinstance(error, dict) else {}
            if permits_fallback(self.values):
                self.values.update(policy)
            self.reject(
                "tool_policy"
                if error.get("name")
                in ("PermissionDeniedError", "PermissionRejectedError", "PermissionRequiredError")
                else "provider_error"
            )
            data = error.get("data")
            data = data if isinstance(data, dict) else {}
            status = data.get("statusCode", error.get("statusCode"))
            if type(status) is int and 100 <= status <= 599:
                self.values["provider_http_status"] = status
        elif kind == "text" and isinstance(part.get("text"), str):
            self.has_text = self.has_text or bool(part["text"].strip())
            if part["text"].strip():
                self.last_text_event = self.values["event_count"]
            self.values["text_characters"] += len(part["text"])
        elif kind == "step_finish":
            reason = part.get("reason")
            self.last_finish = reason if reason in ("stop", "end_turn", "tool-calls") else "other"
            self.values["terminal_finish_seen"] = self.last_finish in ("stop", "end_turn")
            if reason in ("length", "max_tokens", "max_steps"):
                self.reject("output_truncated")
        elif kind == "tool_use":
            tool = part.get("tool")
            bucket = tool if isinstance(tool, str) and tool in TOOL_NAMES else "other"
            self.values["tools"][bucket] += 1
            if bucket == "other":
                self.reject("tool_policy")
            state = part.get("state")
            state = state if isinstance(state, dict) else {}
            status = state.get("status")
            identity = str(part.get("callID") or part.get("id") or bucket)
            identity = hashlib.sha256(identity.encode("utf-8")).hexdigest()
            if status in ("pending", "running"):
                self.pending.add(identity)
            elif status in ("completed", "error"):
                self.pending.discard(identity)
                self.values["tool_errors"] += int(status == "error")
                if status == "error":
                    self.last_tool_error_event = self.values["event_count"]
            else:
                self.values["invalid_event_lines"] += 1
            inputs = state.get("input")
            inputs = inputs if isinstance(inputs, dict) else {}
            if bucket in {"edit", "write"}:
                path = inputs.get("filePath", inputs.get("path", inputs.get("file_path")))
                if (
                    isinstance(path, str)
                    and path not in self.scope["files"]
                    and path not in {str(self.root / p) for p in self.scope["files"]}
                ):
                    self.reject("tool_policy")
            if bucket in {"patch", "apply_patch"}:
                patch = inputs.get("patchText", inputs.get("patch"))
                if isinstance(patch, str):
                    allowed = set(self.scope["files"]) | {
                        str(self.root / path) for path in self.scope["files"]
                    }
                    for patch_line in patch.splitlines():
                        if patch_line.startswith(("*** Delete File:", "*** Move to:")):
                            self.reject("tool_policy")
                        for header in ("*** Update File: ", "*** Add File: "):
                            if (
                                patch_line.startswith(header)
                                and patch_line[len(header) :] not in allowed
                            ):
                                self.reject("tool_policy")
                elif status == "completed":
                    self.values["invalid_event_lines"] += 1
            if bucket == "skill" and status == "completed":
                name = inputs.get("id", inputs.get("name"))
                if isinstance(name, str):
                    name = name.removeprefix("superpowers:").removeprefix("superpowers/")
                self.values["skills"][name if name in SKILL_NAMES else "other"] += 1

    def finish(self) -> str | None:
        if self.buffer:
            self.line(bytes(self.buffer))
            self.buffer.clear()
        self.values["pending_tools"] = len(self.pending)
        if self.code:
            return self.code
        if self.values["invalid_event_lines"]:
            return "invalid_events"
        if self.pending or self.last_finish not in {None, "stop", "end_turn"}:
            return "incomplete_tools"
        # A permitted read/edit can fail and then be corrected by the model.
        # Keep its count, but let a complete candidate and normal ending pass.
        # v2.3.0 legitimately omits step_finish when token metadata is absent.
        if self.last_tool_error_event > self.last_text_event:
            return "tool_error"
        if not self.has_text:
            return "empty_response"
        return None


def _process_table() -> dict[int, tuple[int, int, str]]:
    """PID -> (parent PID, start ticks, state), never command lines or args."""
    result = {}
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            fields = (entry / "stat").read_text().rpartition(")")[2].split()
            result[int(entry.name)] = (int(fields[1]), int(fields[19]), fields[0])
        except (FileNotFoundError, ProcessLookupError, PermissionError, ValueError, IndexError):
            continue
    return result


def _descendants(
    parent: int, table: dict[int, tuple[int, int, str]], excluded: set[tuple[int, int]]
) -> dict[int, tuple[int, int, str]]:
    owned: dict[int, tuple[int, int, str]] = {}
    frontier = {parent}
    while frontier:
        children = {
            pid: values
            for pid, values in table.items()
            if values[0] in frontier and (pid, values[1]) not in excluded
        }
        owned.update(children)
        frontier = set(children) - frontier
    return owned


class ProcessBoundary:
    """Reap this attempt's descendants, including the detached V2 server.

    Standalone OpenCode starts a new session for its server. A process-group
    kill alone cannot reach it. Linux's unprivileged child-subreaper setting
    reparents orphan descendants to this controller so they remain attributable
    even when the CLI exits immediately. Existing children are excluded.
    """

    def __init__(self) -> None:
        self.owner = os.getpid()
        self.libc = ctypes.CDLL(None, use_errno=True)
        self.previous = ctypes.c_int()
        if (
            sys.platform != "linux"
            or not hasattr(os, "pidfd_open")
            or not hasattr(signal, "pidfd_send_signal")
            or self.libc.prctl(PR_GET_CHILD_SUBREAPER, ctypes.byref(self.previous), 0, 0, 0) != 0
        ):
            raise GenerationError("process_cleanup")
        table = _process_table()
        self.excluded = {
            (pid, values[1]) for pid, values in _descendants(self.owner, table, set()).items()
        }
        if self.libc.prctl(PR_SET_CHILD_SUBREAPER, 1, 0, 0, 0) != 0:
            raise GenerationError("process_cleanup")

    def stop(self, process: subprocess.Popen[bytes]) -> None:
        deadline = time.monotonic() + 5
        while True:
            process.poll()
            owned = _descendants(self.owner, _process_table(), self.excluded)
            for pid, (_, started, state) in owned.items():
                if state not in {"Z", "X"}:
                    descriptor = None
                    try:
                        descriptor = os.pidfd_open(pid)
                        current = _process_table().get(pid)
                        if current and current[1] == started:
                            signal.pidfd_send_signal(descriptor, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    finally:
                        if descriptor is not None:
                            os.close(descriptor)
                if pid != process.pid:
                    try:
                        os.waitpid(pid, os.WNOHANG)
                    except ChildProcessError:
                        pass
            process.poll()
            if not _descendants(self.owner, _process_table(), self.excluded):
                if process.returncode is None:
                    raise GenerationError("process_cleanup")
                return
            if time.monotonic() >= deadline:
                raise GenerationError("process_cleanup")
            time.sleep(POLL_SECONDS)

    def close(self) -> None:
        if self.libc.prctl(PR_SET_CHILD_SUBREAPER, self.previous.value, 0, 0, 0) != 0:
            raise GenerationError("process_cleanup")


def execute(
    root: Path, model: str, prompt: str, timeout: float, events: EventMetrics
) -> dict[str, Any]:
    started = time.monotonic()
    counts = {"stdout_bytes": 0, "stderr_bytes": 0}
    code, process = None, None
    exit_code = None
    process_boundary = ProcessBoundary()
    try:
        process = subprocess.Popen(
            [
                "opencode",
                "run",
                "--standalone",
                "--archived",
                "--format",
                "json",
                "--agent",
                "ai-task",
                "--model",
                model,
            ],
            cwd=root,
            env=isolated_environment(model),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
        assert process.stdin and process.stdout and process.stderr
        prompt_bytes = prompt.encode("utf-8")
        prompt_offset = 0
        next_progress = started + PROGRESS_SECONDS
        with selectors.DefaultSelector() as selector:
            for stream, name in (
                (process.stdout, "stdout_bytes"),
                (process.stderr, "stderr_bytes"),
            ):
                os.set_blocking(stream.fileno(), False)
                selector.register(stream, selectors.EVENT_READ, name)
            os.set_blocking(process.stdin.fileno(), False)
            selector.register(process.stdin, selectors.EVENT_WRITE, "prompt")
            stopped = False
            while selector.get_map() or process.poll() is None:
                now = time.monotonic()
                if INTERRUPTED:
                    code = "interrupted"
                    break
                if now - started >= timeout:
                    code = "timeout"
                    break
                if now >= next_progress:
                    print(
                        f"AI generation progress: seconds={int(now - started)}, events={events.values['event_count']}, stdout_bytes={counts['stdout_bytes']}, stderr_bytes={counts['stderr_bytes']}",
                        flush=True,
                    )
                    next_progress = now + PROGRESS_SECONDS
                if not stopped and process.poll() is not None:
                    exit_code = process.returncode
                    process_boundary.stop(process)
                    stopped = True
                ready = selector.select(min(POLL_SECONDS, max(0.0, timeout - (now - started))))
                for key, _ in ready:
                    if key.data == "prompt":
                        try:
                            prompt_offset += os.write(
                                key.fd,
                                prompt_bytes[prompt_offset : prompt_offset + 65_536],
                            )
                        except BrokenPipeError:
                            prompt_offset = len(prompt_bytes)
                        if prompt_offset == len(prompt_bytes):
                            selector.unregister(key.fileobj)
                            process.stdin.close()
                        continue
                    data = os.read(key.fd, 65_536)
                    if not data:
                        selector.unregister(key.fileobj)
                        continue
                    counts[key.data] += len(data)
                    limit = MAX_STDOUT_BYTES if key.data == "stdout_bytes" else MAX_STDERR_BYTES
                    if counts[key.data] > limit:
                        code = "output_limit"
                        break
                    if key.data == "stdout_bytes":
                        events.feed(data)
                    if events.code in {"output_limit", "tool_policy"}:
                        code = events.code
                        break
                if code:
                    break
            exit_code = process.poll() if exit_code is None else exit_code
    except OSError:
        code = "cli_unavailable" if process is None else "controller_error"
    finally:
        cleanup_error = None
        try:
            if process is not None:
                process_boundary.stop(process)
                if exit_code is None:
                    exit_code = process.returncode
        except Exception:
            cleanup_error = GenerationError("process_cleanup")
        finally:
            if process is not None:
                for cleanup_stream in (process.stdout, process.stderr, process.stdin):
                    if cleanup_stream is not None:
                        try:
                            cleanup_stream.close()
                        except OSError:
                            cleanup_error = cleanup_error or GenerationError("process_cleanup")
            try:
                process_boundary.close()
            except Exception:
                cleanup_error = cleanup_error or GenerationError("process_cleanup")
        if cleanup_error:
            raise cleanup_error from None
    event_code = events.finish()
    if event_code == "tool_policy":
        code = event_code
    elif not code:
        code = event_code if event_code == "provider_error" or exit_code == 0 else "cli_error"
    return {
        "code": code,
        "exit_code": exit_code,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        **counts,
        **events.values,
    }


def write_diagnostics(temp: Path, report: dict[str, Any]) -> None:
    # Atomic replacement cannot follow a model-planted final symlink. No raw
    # output, exception messages, paths, arguments or prompt text enter report.
    name = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=temp, delete=False
        ) as target:
            name = target.name
            json.dump(report, target, indent=2)
            target.write("\n")
        os.replace(name, temp / "generation-diagnostics.json")
    except OSError:
        raise GenerationError("diagnostics_unavailable") from None
    finally:
        if name:
            try:
                Path(name).unlink(missing_ok=True)
            except OSError:
                pass


def build_completion_prompt(prompt: str, missing_required: list[str]) -> str:
    """Only trusted scope-derived feedback enters the private follow-up prompt."""
    follow_up = (
        prompt + "\n\nTRUSTED CONTROLLER COMPLETENESS FEEDBACK: "
        "Your previous attempt ended normally, but the candidate is incomplete. "
        "The current checkout retains its validated in-scope changes. Review and preserve "
        "those changes, then complete the missing required files from the approved plan. "
        "Each required file needs a meaningful approved change relative to the original "
        "base; do not make cosmetic edits merely to satisfy this check. The original "
        "scope, creation permissions and all other restrictions remain unchanged. "
        "If the approved plan cannot be completed within that scope, report the blocker. "
        "This is the only completion attempt; finish the complete scoped patch and end.\n"
        + json.dumps(
            {"code": "required_missing", "missing_required_files": missing_required},
            ensure_ascii=False,
        )
    )
    if len(follow_up.encode("utf-8")) > MAX_PROMPT_BYTES:
        raise GenerationError("prompt_limit")
    return follow_up


def run_generation(root: Path, temp: Path, mode: str, model: str) -> dict[str, Any]:
    report: dict[str, Any] = {
        "schema_version": 1,
        "mode": mode if mode in MODE_LIMITS else "unknown",
        "status": "failure",
        "attempts": [],
    }
    started = time.monotonic()
    safe_temp = (
        temp.is_dir()
        and not temp.is_symlink()
        and not temp.resolve().is_relative_to(root.resolve())
    )
    try:
        if mode not in MODE_LIMITS:
            raise GenerationError("invalid_mode")
        if not safe_temp:
            raise GenerationError("unsafe_input")
        primary, total = MODE_LIMITS[mode]
        report.update(primary_limit_seconds=primary, total_limit_seconds=total)
        inputs = {name: _read_regular(temp / name, 4_000_000) for name in INPUT_NAMES}
        context = json.loads(inputs["task-context.json"], object_pairs_hook=no_duplicates)
        router = json.loads(inputs["model.json"], object_pairs_hook=no_duplicates)
        if not isinstance(context, dict):
            raise GenerationError("invalid_context")
        models, probes = verified_models(model, router, mode)
        report["router_probes"] = probes
        if len(inputs["task-prompt.txt"]) > MAX_PROMPT_BYTES:
            raise GenerationError("prompt_limit")
        prompt = inputs["task-prompt.txt"].decode("utf-8")
        if not prompt.strip() or "\0" in prompt:
            raise GenerationError("unsafe_input")
        boundary = CandidateBoundary(root, temp, context, mode)
        report["scope_counts"] = {
            name: len(boundary.scope[name]) for name in ("files", "create", "required")
        }
        candidate_model, phase, attempt_prompt = models[0], "initial", prompt
        for number in range(1, 3):
            remaining = total - (time.monotonic() - started)
            if remaining <= 0 or INTERRUPTED:
                raise GenerationError("interrupted" if INTERRUPTED else "budget_exhausted")
            limit = min(primary if number == 1 else total - primary, remaining)
            attempt: dict[str, Any] = {
                "attempt": number,
                "model": candidate_model,
                "phase": phase,
                "limit_seconds": round(limit, 3),
            }
            report["attempts"].append(attempt)
            print(
                f"AI generation attempt {number}: model={candidate_model}, limit_seconds={round(limit, 1)}",
                flush=True,
            )
            metrics = execute(
                root, candidate_model, attempt_prompt, limit, EventMetrics(root, boundary.scope)
            )
            attempt.update(metrics)
            try:
                changed, counts = boundary.inspect()
            except GenerationError as error:
                attempt["code"] = error.code
                raise
            attempt.update(counts)
            code = metrics["code"] or boundary.completeness(changed)
            attempt["code"] = code or "candidate_generated"
            if code is None:
                report["status"] = "success"
                return report
            if number == 2:
                raise GenerationError(code)
            if mode == "implement" and metrics["code"] is None and code == "required_missing":
                missing = sorted(set(boundary.scope["required"]) - set(changed))
                attempt_prompt = build_completion_prompt(prompt, missing)
                phase = "completion"
                print(
                    f"AI generation completion: prior_code=required_missing, missing_required_files={len(missing)}",
                    flush=True,
                )
                continue
            alternate = fallback_model(models, candidate_model, {candidate_model}, metrics)
            if code not in RETRYABLE or alternate is None:
                raise GenerationError(code)
            boundary.rollback()
            attempt["scoped_rollback"] = True
            candidate_model, phase, attempt_prompt = alternate, "fallback", prompt
            print(
                f"AI generation fallback: prior_code={code}, restored_files={len(changed)}",
                flush=True,
            )
        raise GenerationError("budget_exhausted")
    except GenerationError as error:
        report["failure_code"] = error.code
        raise
    except (ValueError, UnicodeError, TypeError, KeyError):
        report["failure_code"] = "invalid_context"
        raise GenerationError("invalid_context") from None
    except Exception:
        report["failure_code"] = "controller_error"
        raise GenerationError("controller_error") from None
    finally:
        report["elapsed_seconds"] = round(time.monotonic() - started, 3)
        if safe_temp:
            write_diagnostics(temp, report)


def main(argv: list[str] | None = None) -> int:
    global INTERRUPTED
    INTERRUPTED = False
    arguments = sys.argv[1:] if argv is None else argv
    mode = arguments[1] if len(arguments) == 2 and arguments[0] == "--mode" else "unknown"
    temp = Path(os.environ.get("RUNNER_TEMP", "/tmp"))

    def interrupted(_number: int, _frame: Any) -> None:
        global INTERRUPTED
        INTERRUPTED = True

    previous = {
        number: signal.signal(number, interrupted) for number in (signal.SIGTERM, signal.SIGINT)
    }
    try:
        run_generation(Path.cwd(), temp, mode, os.environ.get("MODEL", ""))
    except GenerationError as error:
        print(f"::error::AI generation stopped: {error.code}", file=sys.stderr)
        return 1
    except Exception:
        print("::error::AI generation stopped: controller_error", file=sys.stderr)
        return 1
    finally:
        for number, handler in previous.items():
            signal.signal(number, handler)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
