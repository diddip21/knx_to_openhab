"""Regression coverage for pytest UI marker scoping."""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UI_CONFTEST = ROOT / "tests" / "ui" / "conftest.py"


class _CollectedItem:
    def __init__(self, path):
        self.path = path
        self.markers = []

    def add_marker(self, marker):
        self.markers.append(marker)


def test_ui_collection_hook_marks_only_tests_inside_ui_directory():
    spec = importlib.util.spec_from_file_location("ui_test_conftest", UI_CONFTEST)
    assert spec is not None and spec.loader is not None
    ui_conftest = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ui_conftest)

    core_item = _CollectedItem(ROOT / "tests" / "test_example.py")
    ui_item = _CollectedItem(ROOT / "tests" / "ui" / "test_example.py")

    ui_conftest.pytest_collection_modifyitems(None, [core_item, ui_item])

    assert core_item.markers == []
    assert [marker.name for marker in ui_item.markers] == ["ui"]
