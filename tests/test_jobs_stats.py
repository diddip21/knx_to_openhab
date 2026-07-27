from web_ui.backend.jobs import JobManager


def test_compute_staged_stats_compares_generated_and_live_files(tmp_path):
    openhab_path = tmp_path / "openhab"
    live_path = openhab_path / "items" / "knx.items"
    staged_path = tmp_path / "staging" / "items" / "knx.items"
    live_path.parent.mkdir(parents=True)
    staged_path.parent.mkdir(parents=True)
    live_path.write_text("unchanged\nremoved\n", encoding="utf-8")
    staged_path.write_text("unchanged\nadded one\nadded two\n", encoding="utf-8")

    stats = JobManager.__new__(JobManager)._compute_staged_stats(
        {str(staged_path): str(live_path)}, str(openhab_path)
    )

    assert stats == {
        "items/knx.items": {
            "before": 2,
            "after": 3,
            "delta": 1,
            "added": 2,
            "removed": 1,
            "staged_path": str(staged_path),
            "real_path": str(live_path),
        }
    }


def test_compute_staged_stats_handles_new_file(tmp_path):
    openhab_path = tmp_path / "openhab"
    staged_path = tmp_path / "staging" / "completeness_report.json"
    real_path = openhab_path / "completeness_report.json"
    staged_path.parent.mkdir(parents=True)
    staged_path.write_text("{\n}\n", encoding="utf-8")

    stats = JobManager.__new__(JobManager)._compute_staged_stats(
        {str(staged_path): str(real_path)}, str(openhab_path)
    )

    assert stats["completeness_report.json"]["before"] == 0
    assert stats["completeness_report.json"]["after"] == 2
    assert stats["completeness_report.json"]["added"] == 2
    assert stats["completeness_report.json"]["removed"] == 0
