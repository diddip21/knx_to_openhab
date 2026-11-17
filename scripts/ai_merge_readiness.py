#!/usr/bin/env python3
"""Read-only software merge evidence for any explicitly scoped AI feature PR."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from automation.artifacts import load_json, write_json  # noqa: E402
from automation.scope import BRANCH, COMMAND_REF, SHA, TASK_REF, authorize_task  # noqa: E402

REQUIRED_CI = (
    "Lint (format + typecheck)",
    "Core Tests (Python 3.11)",
    "Core Tests (Python 3.12)",
    "Core Tests (Python 3.13)",
    "UI Tests (Playwright)",
)
IMAGE_PATH = re.compile(r"^docs/screenshots/.+\.(?:png|jpe?g|webp)$", re.IGNORECASE)


def gate(name: str, status: str, reason: str) -> dict[str, str]:
    if status not in {"PASS", "OPEN", "FAIL"}:
        raise ValueError("Invalid audit status")
    return {"name": name, "status": status, "reason": reason}


def evaluate(snapshot: dict[str, Any]) -> list[dict[str, str]]:
    pr = snapshot.get("pr") or {}
    owner = str(snapshot.get("owner") or "")
    sha = str(pr.get("head_sha") or "")
    match = BRANCH.fullmatch(str(pr.get("head_ref") or ""))
    valid = bool(
        match
        and SHA.fullmatch(sha)
        and pr.get("head_repo") == snapshot.get("repository")
        and pr.get("base_ref") == "dev"
        and pr.get("state") == "open"
        and pr.get("author") == "github-actions[bot]"
    )
    result = [
        gate(
            "Branch und Ziel",
            "PASS" if valid else "FAIL",
            (
                "Offener Bot-PR im selben Repository gegen dev"
                if valid
                else "Kein passender offener AI-Bot-PR gegen dev"
            ),
        ),
        gate(
            "Bereit fuer Review",
            "PASS" if pr.get("draft") is False else "OPEN",
            "Ready for review" if pr.get("draft") is False else "Noch Draft oder Status unbekannt",
        ),
        gate(
            "Merge-Konflikte",
            "PASS" if pr.get("mergeable") is True else "OPEN",
            "Konfliktfrei" if pr.get("mergeable") is True else "Konflikt oder unbekannter Status",
        ),
    ]
    try:
        command_ref = COMMAND_REF.search(str(pr.get("body") or ""))
        task_ref = TASK_REF.search(str(pr.get("body") or ""))
        if not valid or match is None or command_ref is None or task_ref is None:
            raise ValueError("Referenz auf ausdruecklich dateibegrenzten Auftrag fehlt")
        number, version, _ = map(int, match.groups())
        comments = snapshot.get("issue_comments") or []
        command = next(c for c in comments if c.get("id") == int(command_ref.group(1)))
        approved = authorize_task(
            snapshot.get("issue") or {},
            comments,
            command,
            owner,
            owner,
            expected_issue_number=number,
        )
        saved = json.loads(task_ref.group(1))
        if not isinstance(saved, dict):
            raise ValueError("Invalid task reference")
        if approved["version"] != version or not SHA.fullmatch(
            str(saved.get("base_commit_sha", ""))
        ):
            raise ValueError("Plan oder Basisreferenz stimmt nicht")
        for key in (
            "issue_number",
            "version",
            "command_comment_id",
            "command_sha256",
            "plan_sha256",
            "scope_sha256",
        ):
            if saved.get(key) != approved[key]:
                raise ValueError(f"Auftragsreferenz stimmt nicht: {key}")
        approval = gate(
            "Plan und Owner-Freigabe",
            "PASS",
            f"Issue #{number}, Plan v{version}, unveraenderter Plan und Dateiumfang",
        )
    except (KeyError, TypeError, ValueError, StopIteration) as exc:
        approval = gate("Plan und Owner-Freigabe", "OPEN", str(exc) or "Originalbefehl fehlt")
    result.append(approval)
    checks: dict[str, dict[str, Any]] = {}
    for record in snapshot.get("checks") or []:
        name = record.get("name")
        if (
            name not in REQUIRED_CI
            or record.get("head_sha") != sha
            or record.get("app_slug") != "github-actions"
        ):
            continue
        previous = checks.get(name)
        if previous is None or (str(record.get("started_at") or ""), int(record.get("id") or 0)) > (
            str(previous.get("started_at") or ""),
            int(previous.get("id") or 0),
        ):
            checks[name] = record
    missing = [name for name in REQUIRED_CI if name not in checks]
    bad = [
        name
        for name, check in checks.items()
        if check.get("status") != "completed" or check.get("conclusion") != "success"
    ]
    result.append(
        gate(
            "CI am aktuellen Commit",
            "PASS" if not (missing or bad) else "OPEN",
            (
                f"Alle fuenf GitHub-Actions-Gates erfolgreich auf {sha[:8]}"
                if not (missing or bad)
                else f"Fehlend: {missing}; nicht erfolgreich: {bad}"
            ),
        )
    )
    latest: dict[str, dict[str, Any]] = {}
    for review in snapshot.get("reviews") or []:
        user = review.get("user") or {}
        login = str(user.get("login") or "").lower()
        if (
            not login
            or user.get("type") != "User"
            or login == str(pr.get("author") or "").lower()
            or review.get("state") not in {"APPROVED", "CHANGES_REQUESTED", "DISMISSED"}
        ):
            continue
        if login not in latest or str(review.get("submitted_at") or "") > str(
            latest[login].get("submitted_at") or ""
        ):
            latest[login] = review
    approvals = [
        name
        for name, review in latest.items()
        if review.get("state") == "APPROVED" and review.get("commit_id") == sha
    ]
    objections = [
        name for name, review in latest.items() if review.get("state") == "CHANGES_REQUESTED"
    ]
    result.append(
        gate(
            "Unabhaengiges Code-Review",
            "PASS" if approvals and not objections else "OPEN",
            (
                "Aktuelles menschliches APPROVED: " + ", ".join(approvals)
                if approvals and not objections
                else "Menschliche Freigabe auf aktueller SHA fehlt oder Aenderungen angefordert"
            ),
        )
    )
    unresolved = snapshot.get("unresolved_threads")
    result.append(
        gate(
            "Review-Diskussionen",
            "PASS" if type(unresolved) is int and unresolved == 0 else "OPEN",
            (
                "Keine offenen Threads"
                if type(unresolved) is int and unresolved == 0
                else "Offene oder nicht gelesene Review-Threads"
            ),
        )
    )
    files = snapshot.get("files")
    ui_changed = isinstance(files, list) and any(
        str(file.get("filename") or "").startswith(("web_ui/static/", "web_ui/templates/"))
        for file in files
    )
    images = [
        f
        for f in files or []
        if IMAGE_PATH.fullmatch(str(f.get("filename") or "")) and f.get("status") != "removed"
    ]
    ui_ok = isinstance(files, list) and (not ui_changed or bool(images))
    result.append(
        gate(
            "UI-Belege",
            "PASS" if ui_ok else "OPEN",
            (
                (
                    "Keine UI-Aenderung"
                    if not ui_changed
                    else f"{len(images)} Bilddateien; menschliche Sichtpruefung bleibt erforderlich"
                )
                if ui_ok
                else "Diff unbekannt oder reale Screenshot-Dateien fehlen"
            ),
        )
    )
    return result


def summarize(pr: dict[str, Any], gates: list[dict[str, str]]) -> str:
    def safe(value: Any) -> str:
        return str(value).replace("|", "/").replace("\r", " ").replace("\n", " ")[:600]

    lines = [
        "### AI Software Merge-Readiness (read-only)",
        "",
        f"PR #{safe(pr.get('number'))}, HEAD `{safe(pr.get('head_sha'))}`",
        "",
        "| Gate | Status | Nachweis oder Blocker |",
        "|---|---|---|",
    ]
    lines.extend(f"| {safe(g['name'])} | {g['status']} | {safe(g['reason'])} |" for g in gates)
    lines.extend(
        [
            "",
            (
                "**Software-Gates belegt.**"
                if all(g["status"] == "PASS" for g in gates)
                else "**Noch nicht merge-ready: offene Nachweise.**"
            ),
            "",
            "Keine automatische Merge-Freigabe. Der Owner entscheidet. "
            "Der Softwarebericht behauptet keine Validierung an realen Geraeten.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    snapshot = load_json(args.snapshot)
    gates = evaluate(snapshot)
    report = {
        "pr": snapshot.get("pr", {}).get("number"),
        "sha": snapshot.get("pr", {}).get("head_sha"),
        "ready": all(g["status"] == "PASS" for g in gates),
        "gates": gates,
    }
    write_json(args.report, report)
    summary = summarize(snapshot.get("pr") or {}, gates)
    print(summary)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with Path(os.environ["GITHUB_STEP_SUMMARY"]).open("a", encoding="utf-8") as out:
            out.write(summary)
    return 0 if report["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
