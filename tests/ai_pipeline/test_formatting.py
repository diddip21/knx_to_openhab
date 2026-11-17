"""Use real formatters with trusted settings and reject unapproved files first."""

import pytest
from automation.formatting import format_candidate

from .helpers import ROOT, context, git, init_repo


def test_formatters_change_only_approved_text_and_collect_again(tmp_path):
    root = init_repo(tmp_path / "candidate")
    (root / "pyproject.toml").write_text("this is invalid candidate TOML", encoding="utf-8")
    git(root, "add", "pyproject.toml")
    git(root, "commit", "-qm", "candidate configuration fixture")
    approved = context(root)
    (root / "feature.py").write_text("value=1   \n", encoding="utf-8")
    (root / "tests/test_feature.py").write_text(
        "def test_value():\n assert True\n", encoding="utf-8"
    )
    # Candidate formatter configuration must not control trusted formatting.
    (root / "docs/feature.md").write_text("# Existing documentation\n", encoding="utf-8")
    format_candidate(root, ROOT, approved, repair=False)
    assert (root / "feature.py").read_text() == "value = 1\n"
    assert "    assert True" in (root / "tests/test_feature.py").read_text()
    assert (root / "docs/feature.md").read_text() == "# Existing documentation\n"


def test_formatter_refuses_unapproved_file_before_invoking_tools(tmp_path):
    root = init_repo(tmp_path / "candidate")
    approved = context(root)
    (root / "feature.py").write_text("value=1\n", encoding="utf-8")
    (root / "unexpected.py").write_text("value=2\n", encoding="utf-8")
    with pytest.raises(ValueError, match="allowlist"):
        format_candidate(root, ROOT, approved, repair=False)
    assert (root / "feature.py").read_text() == "value=1\n"
