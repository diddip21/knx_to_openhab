"""An opt-in, unpublished real planner replay with interruption/resume evidence."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import issue_bot  # noqa: E402
from automation import planner_runner  # noqa: E402
from automation.model_response import ModelResponseError  # noqa: E402


def prepare(temp: Path) -> None:
    source = json.loads((temp / "planner-diagnostic-source.json").read_text(encoding="utf-8"))
    issue = source["issue"]
    if issue.get("state") != "open" or issue.get("pull_request"):
        raise ValueError("Diagnostic requires an open issue")
    previous = issue_bot.last_bot_state(source["comments"])
    answers = issue_bot.pending_replan_request(source["comments"], source["owner"], 0)
    decision = {
        "operation": "plan",
        "version": previous["state"]["version"] + 1 if previous else 1,
        "digest": issue_bot.issue_digest(issue),
        "issue": issue,
        "previous": previous["body"] if previous else "",
        "answer": (answers or {}).get("body", ""),
        "related_prs": json.loads((temp / "planning-context.json").read_text(encoding="utf-8")),
    }
    (temp / "issue-decision.json").write_text(json.dumps(decision), encoding="utf-8")
    (temp / "issue-prompt.txt").write_text(
        issue_bot.prepare_research_prompt(decision), encoding="utf-8"
    )


def run(temp: Path) -> None:
    router = json.loads((temp / "model-router.json").read_text(encoding="utf-8"))
    report = planner_runner.run_plan(temp, router["selected"], router, checkpoint_seconds=90)
    # No publisher exists in this workflow. The normal JSON/scope/finish gates still ran.
    result = json.loads((temp / "issue-result.json").read_text(encoding="utf-8"))
    resumed = any(attempt["resumed"] for attempt in report["attempts"])
    interrupted = any(
        attempt["code"] == "timeout"
        and attempt.get("graceful_stop")
        and attempt.get("completed_reads", 0) > 0
        and any(later["resumed"] for later in report["attempts"][index + 1 :])
        for index, attempt in enumerate(report["attempts"])
    )
    if (
        result["kind"] != "plan"
        or not resumed
        or not interrupted
        or not report["evidence_available"]
        or report["evidence_read"] != report["evidence_available"]
    ):
        raise ModelResponseError("diagnostic_incomplete")
    # Reference presence is a mechanical check, not a semantic review of the model's claims.
    context = json.loads((temp / "planning-context.json").read_text(encoding="utf-8"))
    markdown = result["comment"]
    available = [s for s in context["evidence"]["sources"] if s["status"] == "available"]
    cited = sum(
        source["url"] in markdown
        or bool(source.get("revision") and source["revision"][:7] in markdown)
        for source in available
    )
    report["evidence_cited"] = cited
    report["private_replay_validated"] = True
    planner_runner.write_diagnostics(temp, report)
    print(
        f"Private plan validated after same-session resume; "
        f"evidence read={report['evidence_read']}, external references={cited}/{len(available)}. "
        "No issue, label, approval or PR was changed. Semantic plan review remains separate."
    )
    (temp / "issue-result.json").unlink()
    (temp / "opencode-events.jsonl").unlink(missing_ok=True)


def main() -> int:
    temp = Path(os.environ["RUNNER_TEMP"])
    try:
        if sys.argv[1:] == ["prepare"]:
            prepare(temp)
        elif sys.argv[1:] == ["run"]:
            run(temp)
        else:
            raise SystemExit("Usage: planner_diagnostic.py prepare|run")
    except ModelResponseError as error:
        print(f"::error::Private planner replay failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
