#!/usr/bin/env python3
"""Fail a real openHAB smoke run on *new* parsing/model errors after deployment.

No catch-all log suppression: a test-only KNX gateway being OFFLINE is expected
and is not a failure unless openHAB emits an ERROR/exception.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

LOG_FILES = (
    Path("/var/log/openhab/openhab.log"),
    Path("/var/log/openhab/events.log"),
)
FATAL = re.compile(
    r"\[\s*(?:ERROR|FATAL)\s*\]|"
    r"\b(?:YAMLException|SAXParseException|JsonParseException|"
    r"InvalidConfigurationException|IllegalArgumentException)\b|"
    r"\b(?:failed|unable|error|invalid)\s+to\s+"
    r"(?:parse|load|read|create|register|resolve|initialize)\b|"
    r"\b(?:parse|parsing|syntax|configuration|channel|item|thing|model)\s+error\b",
    flags=re.IGNORECASE,
)
SUSPICIOUS_WARNING = re.compile(
    r"\[\s*WARN\s*\].*?"
    r"(?:invalid\s+(?:channel|thing|item|config)|"
    r"(?:could\s+not|failed\s+to|unable\s+to)\s+"
    r"(?:parse|load|register|resolve)\b|"
    r"(?:parse|parser|syntax|yaml|configuration)\s+error\b)",
    flags=re.IGNORECASE,
)


def snapshot() -> dict[str, tuple[int, int]]:
    """Return inode and length so previous startup errors cannot mask regressions."""
    result = {}
    for path in LOG_FILES:
        try:
            state = path.stat()
        except FileNotFoundError:
            continue
        result[str(path)] = (state.st_ino, state.st_size)
    return result


def check_since(
    baseline: dict[str, tuple[int, int]], label: str, output: Path
) -> None:
    if not any(path.is_file() for path in LOG_FILES):
        raise AssertionError("openHAB log files are missing; cannot verify deploy logs")
    found = []
    warnings = []
    excerpts = {}
    for path in LOG_FILES:
        if not path.is_file():
            continue
        state = path.stat()
        previous_inode, previous_size = baseline.get(str(path), (-1, 0))
        offset = previous_size if state.st_ino == previous_inode and state.st_size >= previous_size else 0
        with path.open("rb") as stream:
            stream.seek(offset)
            delta = stream.read().decode("utf-8", errors="replace")
        lines = delta.splitlines()
        excerpts[path.name] = {"new_lines": len(lines), "read_offset": offset}
        for line in lines:
            if FATAL.search(line) or SUSPICIOUS_WARNING.search(line):
                found.append({"file": path.name, "line": line[:700]})
            elif "[WARN" in line:
                warnings.append({"file": path.name, "line": line[:350]})
    report = {
        "phase": label,
        "status": "failed" if found else "passed",
        "log_segments": excerpts,
        "fatal_lines": found[:120],
        "warnings": warnings[:70],
    }
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if found:
        summary = "\n".join(f"{item['file']}: {item['line']}" for item in found[:12])
        raise AssertionError(f"New openHAB errors after {label}:\n{summary}")
    print(f"PASS [{label}]: no new openHAB parser, model or ERROR log lines", flush=True)
