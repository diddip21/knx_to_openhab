#!/usr/bin/env python3
"""Compatibility imports for existing AI workflows; the README pilot is retired.

The shared implementation lives in automation/. Keeping these imports avoids
breaking the active issue #89 controllers and the independent readiness PR.
There is deliberately no prepare/collect/recheck CLI or default issue number.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING or __package__:
    from .automation.approval import BOT_LOGIN, COMMAND, PLAN_MARKER, authorize, digest, latest_plan
    from .automation.git_helpers import git
else:
    from automation.approval import BOT_LOGIN, COMMAND, PLAN_MARKER, authorize, digest, latest_plan
    from automation.git_helpers import git

__all__ = ["BOT_LOGIN", "COMMAND", "PLAN_MARKER", "authorize", "digest", "git", "latest_plan"]

if __name__ == "__main__":
    raise SystemExit("The issue #96 README implementation pilot has been retired.")
