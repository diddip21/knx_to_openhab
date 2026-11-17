"""Issue-independent, fail-closed approval checks for trusted controllers."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

BOT_LOGIN = "github-actions[bot]"
COMMAND = re.compile(r"^/ai (?:implement|start) v([1-9][0-9]*)$", re.IGNORECASE)
PLAN_MARKER = re.compile(r"^<!-- knx-issue-bot-state (\{[^\n]*\}) -->")


def digest(issue: dict[str, Any]) -> str:
    payload = json.dumps(
        [issue.get("title", ""), issue.get("body") or ""],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def text_digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def unedited(comment: dict[str, Any]) -> None:
    # Live GitHub comments always have these timestamps. Unit snapshots may omit them.
    if comment.get("updated_at") != comment.get("created_at"):
        raise ValueError("Edited authorization comment: create a new plan/command instead")


def latest_plan(comments: list[dict[str, Any]]) -> dict[str, Any]:
    states = []
    for comment in comments:
        if (comment.get("user") or {}).get("login", "").casefold() != BOT_LOGIN:
            continue
        body = comment.get("body") or ""
        match = PLAN_MARKER.match(body)
        if match is None:
            continue
        try:
            marker = json.loads(match.group(1))
        except ValueError as exc:
            raise ValueError("Malformed trusted planning marker") from exc
        if (
            not isinstance(marker, dict)
            or marker.get("kind") not in {"plan", "questions"}
            or type(marker.get("version")) is not int
            or not 1 <= marker["version"] <= 9999
            or not re.fullmatch(r"[a-f0-9]{64}", str(marker.get("issue_digest", "")))
        ):
            raise ValueError("Invalid trusted planning marker")
        states.append((int(comment["id"]), comment, marker))
    if not states:
        raise ValueError("No trusted approved planning comment found")
    ident, comment, marker = max(states, key=lambda record: record[0])
    unedited(comment)
    if marker["kind"] != "plan":
        raise ValueError("The latest planning response still has questions")
    return {"id": ident, "state": marker, "body": comment["body"]}


def authorize(
    issue: dict[str, Any],
    comments: list[dict[str, Any]],
    command_comment: dict[str, Any],
    actor: str,
    owner: str,
    *,
    expected_issue_number: int,
) -> dict[str, Any]:
    """Verify the owner, current plan, receipt and unchanged issue, not file access."""
    if type(expected_issue_number) is not int or expected_issue_number < 1:
        raise ValueError("A positive issue number from trusted policy is required")
    if not actor or actor.casefold() != owner.casefold():
        raise ValueError("Only the repository owner may authorize implementation")
    if issue.get("number", issue.get("issue_number")) != expected_issue_number:
        raise ValueError(f"Implementation is restricted to issue #{expected_issue_number}")
    if issue.get("state") != "open" or issue.get("pull_request"):
        raise ValueError("Target must be an open issue")
    labels = {
        label.get("name") if isinstance(label, dict) else label for label in issue.get("labels", [])
    }
    if not {"ai:plan", "ai:approved"}.issubset(labels) or "ai:waiting" in labels:
        raise ValueError("The current plan is not approved")
    if (command_comment.get("user") or {}).get("login", "").casefold() != owner.casefold():
        raise ValueError("Implementation command must be authored by the owner")
    body = str(command_comment.get("body") or "").strip()
    header = body.splitlines()[0] if body else ""
    implementation = COMMAND.fullmatch(header)
    if not implementation:
        raise ValueError("Expected exact command header: /ai start vN or /ai implement vN")
    version = int(implementation.group(1))
    plan = latest_plan(comments)
    if plan["state"]["version"] != version or plan["state"]["issue_digest"] != digest(issue):
        raise ValueError("Plan version or issue digest is stale")
    cmd_id = int(command_comment["id"])
    live = next((c for c in comments if c.get("id") == cmd_id), None)
    if (
        live is None
        or (live.get("body") or "").strip() != body
        or (live.get("user") or {}).get("login", "").casefold() != owner.casefold()
    ):
        raise ValueError("Implementation command is not in the live comment history")
    unedited(live)
    if cmd_id <= plan["id"]:
        raise ValueError("Implementation command predates the latest plan")
    approvals = [
        comment
        for comment in comments
        if plan["id"] < int(comment.get("id") or 0) < cmd_id
        and (comment.get("user") or {}).get("login", "").casefold() == owner.casefold()
        and (comment.get("body") or "").strip().casefold() == f"/ai approve v{version}"
    ]
    if not approvals:
        raise ValueError("No matching owner approval after the latest plan")
    approval = max(approvals, key=lambda item: int(item["id"]))
    unedited(approval)
    receipts = [
        c
        for c in comments
        if int(approval["id"]) < int(c.get("id") or 0) < cmd_id
        and (c.get("user") or {}).get("login", "").casefold() == BOT_LOGIN
        and (c.get("body") or "").startswith(f"\u2705 **Plan v{version} freigegeben.**")
    ]
    if not receipts:
        raise ValueError("The planning workflow has not confirmed approval")
    unedited(max(receipts, key=lambda c: int(c["id"])))
    return {
        "issue_number": expected_issue_number,
        "version": version,
        "digest": digest(issue),
        "plan_comment_id": plan["id"],
        "plan_sha256": text_digest(plan["body"]),
        "approval_comment_id": int(approval["id"]),
        "command_comment_id": cmd_id,
        "command_sha256": text_digest(body),
        "plan": plan["body"],
    }
