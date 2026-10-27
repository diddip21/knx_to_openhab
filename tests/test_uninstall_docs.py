from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_uninstall_guides_describe_default_retention_and_confirmed_purge():
    for doc_path in (ROOT / "installer" / "README.md", ROOT / "docs" / "PRODUCTION_GUIDE.md"):
        content = doc_path.read_text(encoding="utf-8").lower()
        assert "--purge" in content
        assert "uninstall" in content
        assert "backups" in content
        assert "runtime" in content
        assert "retain" in content
        assert "purge" in content
        assert "type" in content
