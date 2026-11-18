"""Replay planning privately, without issuing an owner command or publishing a plan."""

from __future__ import annotations

import importlib
import json
import os
import sys
from pathlib import Path
from typing import Any


def prepare(source: dict[str, Any], temp: Path, bot: Any) -> None:
    issue = source["issue"]
    if issue.get("state") != "open" or issue.get("pull_request"):
        raise ValueError("Diagnostic requires an open issue")
    previous = bot.last_bot_state(source["comments"])
    # This is a private replay, not a new planning request or an authorization.
    decision = {
        "operation": "plan",
        "version": previous["state"]["version"] if previous else 1,
        "digest": bot.issue_digest(issue),
        "issue": issue,
        "previous": previous["body"] if previous else "",
        "answer": (
            "Rein lesender Diagnoselauf mit aktuellem Issue-/PR-Kontext. "
            "Erzeuge die normale strukturierte Planantwort, ohne Dateien zu ändern. "
            "Die Antwort wird nicht veröffentlicht und erteilt keine Freigabe."
        ),
        "related_prs": source["related"],
    }
    prompt = bot.make_prompt(decision)
    (temp / "issue-decision.json").write_text(json.dumps(decision), encoding="utf-8")
    (temp / "issue-prompt.txt").write_text(prompt, encoding="utf-8")


def main() -> int:
    if len(sys.argv) != 3 or sys.argv[1] not in {"prepare", "run"}:
        raise SystemExit("Usage: planner_diagnostic.py prepare|run TRUSTED_ROOT")
    trusted = Path(sys.argv[2]).resolve()
    sys.path.insert(0, str(trusted / "scripts"))
    bot = importlib.import_module("issue_bot")
    temp = Path(os.environ["RUNNER_TEMP"])
    if sys.argv[1] == "prepare":
        source = json.loads((temp / "planner-diagnostic-source.json").read_text(encoding="utf-8"))
        prepare(source, temp, bot)
        return 0
    runner = importlib.import_module("automation.planner_runner")
    router = json.loads((temp / "model-router.json").read_text(encoding="utf-8"))
    try:
        runner.run_plan(temp, os.environ.get("MODEL", ""), router)
    except runner.ModelResponseError as error:
        print(f"::error::Unpublished planner diagnostic stopped: {error}", file=sys.stderr)
        return 1
    print("Validated a private planning response. No issue, approval, label or PR was changed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
