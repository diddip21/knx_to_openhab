"""Issue-independent approval checks for trusted repository controllers.

Callers must supply the issue number from their own trusted policy. Validating
an approval does not grant file-write permissions or enable a new agent.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

BOT_LOGIN = "github-actions[bot]"
COMMAND = re.compile(r"^/ai implement v([1-9][0-9]*)$", re.IGNORECASE)
PLAN_MARKER = re.compile(r"^<!-- knx-issue-bot-state (\{[^\n]*\}) -->")


def digest(issue: dict[str, Any]) -> str:
    payload = json.dumps(
        [issue.get("title", ""), issue.get("body") or ""],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def latest_plan(comments: list[dict[str, Any]]) -> dict[str, Any]:
    plans = []
    for comment in comments:
        if (comment.get("user") or {}).get("login", "").casefold() != BOT_LOGIN:
            continue
        body = comment.get("body") or ""
        match = PLAN_MARKER.match(body)
        if match is None:
            continue
        try:
            marker = json.loads(match.group(1))
        except ValueError:
            continue
        if (
            isinstance(marker, dict)
            and marker.get("kind") == "plan"
            and type(marker.get("version")) is int
            and isinstance(marker.get("issue_digest"), str)
            and re.fullmatch(r"[a-f0-9]{64}", marker["issue_digest"])
        ):
            plans.append({"id": int(comment["id"]), "state": marker, "body": body})
    if not plans:
        raise ValueError("No trusted approved planning comment found")
    return max(plans, key=lambda plan: plan["id"])


def authorize(
    issue: dict[str, Any],
    comments: list[dict[str, Any]],
    command_comment: dict[str, Any],
    actor: str,
    owner: str,
    *,
    expected_issue_number: int,
) -> dict[str, Any]:
    """Require the owner, latest plan, exact approval and unchanged issue."""
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
    implementation = COMMAND.fullmatch((command_comment.get("body") or "").strip())
    if not implementation:
        raise ValueError("Expected exact command: /ai implement vN")
    version = int(implementation.group(1))
    plan = latest_plan(comments)
    marker = plan["state"]
    if marker["version"] != version or marker["issue_digest"] != digest(issue):
        raise ValueError("Plan version or issue digest is stale")
    cmd_id = int(command_comment["id"])
    if not any(
        int(comment.get("id") or 0) == cmd_id
        and (comment.get("body") or "").strip() == (command_comment.get("body") or "").strip()
        and (comment.get("user") or {}).get("login", "").casefold() == owner.casefold()
        for comment in comments
    ):
        raise ValueError("Implementation command is not in the live comment history")
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
    confirmed = any(
        int(approval["id"]) < int(comment.get("id") or 0) < cmd_id
        and (comment.get("user") or {}).get("login", "").casefold() == BOT_LOGIN
        and (comment.get("body") or "").startswith(f"\u2705 **Plan v{version} freigegeben.**")
        for comment in comments
    )
    if not confirmed:
        raise ValueError("The planning workflow has not confirmed approval")
    return {
        "issue_number": expected_issue_number,
        "version": version,
        "digest": marker["issue_digest"],
        "plan_comment_id": plan["id"],
        "approval_comment_id": int(approval["id"]),
        "command_comment_id": cmd_id,
        "plan": plan["body"],
    }
