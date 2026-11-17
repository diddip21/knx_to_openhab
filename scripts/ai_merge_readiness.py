#!/usr/bin/env python3
"""Read-only, fail-closed merge-readiness evidence for approved AI feature PRs.

This script reads a bounded GitHub API snapshot from a trusted workflow. It
does not clone candidate code, execute generated tests, write GitHub state or
replace a maintainer's software review.
"""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from typing import Any

from issue_impl import authorize

AI_BRANCH = re.compile(r"^ai/issue-(\d+)-plan-v([1-9]\d*)-run-([1-9]\d*)$")
SHA = re.compile(r"^[0-9a-f]{40}$")
COMMAND_ID = re.compile(r"<!-- ai-implementation-command: ([1-9]\d*) -->")
IMAGE_PATH = re.compile(r"^docs/screenshots/.+\.(?:png|jpe?g|webp)$", re.IGNORECASE)
REQUIRED_CI = (
    "Lint (format + typecheck)",
    "Core Tests (Python 3.11)",
    "Core Tests (Python 3.12)",
    "Core Tests (Python 3.13)",
    "UI Tests (Playwright)",
)


def gate(name: str, status: str, reason: str) -> dict[str, str]:
    if status not in {"PASS", "OPEN", "FAIL"}:
        raise ValueError("Invalid audit gate")
    return {"name": name, "status": status, "reason": reason}


def evaluate(snapshot: dict[str, Any]) -> list[dict[str, str]]:
    """Every prerequisite must be proven; unknown and stale data remain OPEN."""
    results: list[dict[str, str]] = []
    pr = snapshot.get("pr") or {}
    owner = snapshot.get("owner") or ""
    branch = str(pr.get("head_ref") or "")
    sha = str(pr.get("head_sha") or "")
    match = AI_BRANCH.fullmatch(branch)
    valid_source = (
        match is not None
        and bool(SHA.fullmatch(sha))
        and pr.get("head_repo") == snapshot.get("repository")
        and pr.get("base_ref") == "dev"
        and pr.get("state") == "open"
    )
    results.append(
        gate(
            "Branch und Ziel",
            "PASS" if valid_source else "FAIL",
            (
                "Offener KI-Feature-PR aus demselben Repository, Base dev, gültiger HEAD"
                if valid_source
                else "Nur offene ai/issue-N-Plan-PRs aus diesem Repository gegen dev"
            ),
        )
    )
    draft = pr.get("draft")
    results.append(
        gate(
            "Bereit für Review",
            "PASS" if draft is False else "OPEN",
            "Ready for review" if draft is False else "Noch Draft; nur Owner gibt frei",
        )
    )
    results.append(
        gate(
            "Merge-Konflikte",
            "PASS" if pr.get("mergeable") is True else "OPEN",
            (
                "GitHub meldet keinen Konflikt"
                if pr.get("mergeable") is True
                else "Mergeability ist unbekannt oder Konflikt liegt vor"
            ),
        )
    )
    issue_number = int(match.group(1)) if match else None
    plan_version = int(match.group(2)) if match else None

    issue = snapshot.get("issue") or {}
    issue_comments = snapshot.get("issue_comments") or []
    command_match = COMMAND_ID.search(str(pr.get("body") or ""))
    try:
        if (
            not valid_source
            or command_match is None
            or issue_number is None
            or plan_version is None
        ):
            raise ValueError("PR fehlt die gültige Implementierungs-/Planreferenz")
        command_id = int(command_match.group(1))
        command = next(
            (c for c in issue_comments if c.get("id") == command_id),
            None,
        )
        if command is None or issue.get("number") != issue_number:
            raise ValueError("Originaler Issue-Befehl fehlt oder Issue-Nummer weicht ab")
        approved = authorize(
            issue,
            issue_comments,
            command,
            owner,
            owner,
            expected_issue_number=issue_number,
        )
        if approved["version"] != plan_version:
            raise ValueError("Freigegebene Planversion stimmt nicht mit PR-Branch überein")
        approval_status = gate(
            "Plan und Owner-Freigabe",
            "PASS",
            f"Issue #{issue_number}, Plan v{plan_version}, gültiger Digest und Owner-Befehl",
        )
    except (TypeError, ValueError, StopIteration) as exc:
        approval_status = gate("Plan und Owner-Freigabe", "OPEN", str(exc))
    results.append(approval_status)

    checks = snapshot.get("checks") or []
    by_name: dict[str, dict[str, Any]] = {}
    for record in checks:
        name = record.get("name")
        if name not in REQUIRED_CI:
            continue
        if record.get("head_sha") != sha:
            continue
        previous = by_name.get(name)
        # check-runs are delivered newest first, but timestamps make this
        # independent of the API response ordering.
        if previous is None or (
            str(record.get("started_at") or ""),
            str(record.get("id") or ""),
        ) > (str(previous.get("started_at") or ""), str(previous.get("id") or "")):
            by_name[name] = record
    missing = [name for name in REQUIRED_CI if name not in by_name]
    bad = [
        name
        for name in REQUIRED_CI
        if name in by_name
        and (
            by_name[name].get("status") != "completed"
            or by_name[name].get("conclusion") != "success"
        )
    ]
    results.append(
        gate(
            "CI am aktuellen Commit",
            "PASS" if not (missing or bad) else "OPEN",
            (
                "Lint, Python 3.11/3.12/3.13 und Playwright erfolgreich auf " + sha[:8]
                if not (missing or bad)
                else f"Fehlend: {missing}; nicht erfolgreich: {bad}; HEAD {sha[:8]}"
            ),
        )
    )

    reviews = snapshot.get("reviews") or []
    latest_review_by_user: dict[str, dict[str, Any]] = {}
    for review in reviews:
        author = (review.get("user") or {}).get("login", "").lower()
        if not author:
            continue
        previous = latest_review_by_user.get(author)
        if previous is None or str(review.get("submitted_at") or "") > str(
            previous.get("submitted_at") or ""
        ):
            latest_review_by_user[author] = review
    approvals = [
        author
        for author, review in latest_review_by_user.items()
        if author != str(pr.get("author") or "").lower()
        and (review.get("user") or {}).get("type") == "User"
        and review.get("state") == "APPROVED"
        and review.get("commit_id") == sha
    ]
    results.append(
        gate(
            "Unabhängiges Code-Review",
            "PASS" if approvals else "OPEN",
            (
                "Aktuelle Freigabe auf dem HEAD durch " + ", ".join(approvals)
                if approvals
                else "Keine menschliche APPROVED-Review (nicht vom PR-Autor) auf der aktuellen SHA; "
                "ein Codex-COMMENTED ist keine Freigabe"
            ),
        )
    )

    unresolved = snapshot.get("unresolved_threads")
    results.append(
        gate(
            "Review-Diskussionen",
            "PASS" if unresolved == 0 else "OPEN",
            (
                "Keine offenen Review-Threads"
                if unresolved == 0
                else f"{unresolved!r} offene oder nicht ausgelesene Review-Threads"
            ),
        )
    )
    if issue_number == 89:
        screenshot_files = [
            file["filename"]
            for file in snapshot.get("files") or []
            if IMAGE_PATH.fullmatch(str(file.get("filename") or ""))
            and file.get("status") != "removed"
        ]
        results.append(
            gate(
                "UI-Belege",
                "PASS" if screenshot_files else "OPEN",
                (
                    f"{len(screenshot_files)} Screenshot-Dateien im PR"
                    if screenshot_files
                    else "Keine echten Screenshots unter docs/screenshots/ im Diff"
                ),
            )
        )
    return results


def summarize(pr: dict[str, Any], gates: list[dict[str, str]]) -> str:
    def safe(text: Any) -> str:
        # GitHub API data are untrusted; avoid Markdown table injection.
        return str(text).replace("|", "/").replace("\r", " ").replace("\n", " ")[:600]

    lines = [
        "### AI Merge-Readiness (read-only)",
        "",
        f"PR #{safe(pr.get('number'))}, HEAD `{safe(pr.get('head_sha'))}`, Base "
        f"`{safe(pr.get('base_ref'))}`",
        "",
        "| Gate | Status | Nachweis oder Blocker |",
        "|---|---|---|",
    ]
    for item in gates:
        lines.append(f"| {safe(item['name'])} | {item['status']} | {safe(item['reason'])} |")
    ready = all(item["status"] == "PASS" for item in gates)
    lines.extend(
        [
            "",
            (
                "**Software-Merge-Gates vollständig belegbar**"
                if ready
                else "**Noch NICHT merge-ready: offene/fehlende Nachweise.**"
            ),
            "",
            "Das ist keine automatische Merge-Freigabe. Der Owner prüft den "
            "Softwarebericht und entscheidet über den Merge selbst.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    snapshot = json.loads(args.snapshot.read_text(encoding="utf-8"))
    gates = evaluate(snapshot)
    report = {
        "pr": snapshot.get("pr", {}).get("number"),
        "sha": snapshot.get("pr", {}).get("head_sha"),
        "ready": all(item["status"] == "PASS" for item in gates),
        "gates": gates,
    }
    args.report.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    summary = summarize(snapshot.get("pr") or {}, gates)
    print(summary)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with Path(os.environ["GITHUB_STEP_SUMMARY"]).open("a", encoding="utf-8") as out:
            out.write(summary)
    return 0 if report["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
