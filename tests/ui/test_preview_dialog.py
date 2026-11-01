import json
import re

import pytest
from playwright.sync_api import Page, expect

JOB_ID = "job-preview"


def _setup_preview_routes(page: Page, backups=None):
    stats = {
        "items/knx.items": {
            "before": 1,
            "after": 2,
            "delta": 1,
            "added": 1,
            "removed": 0,
        },
        "completeness_report.json": {
            "before": 1,
            "after": 1,
            "delta": 0,
            "added": 0,
            "removed": 0,
            "staged_path": "openhab/completeness_report.json",
        },
        "unknown_report.json": {
            "before": 1,
            "after": 1,
            "delta": 0,
            "added": 0,
            "removed": 0,
            "staged_path": "openhab/unknown_report.json",
        },
    }

    jobs = [
        {
            "id": JOB_ID,
            "name": "Preview Job",
            "status": "completed",
            "staged": True,
            "deployed": False,
            "backups": backups or [],
            "created": 1700000000,
            "stats": stats,
        }
    ]

    report_payload = {
        "summary": {
            "missing_required": 1,
            "recommended_missing": 0,
            "total_things_checked": 10,
        },
        "missing_required": [
            {
                "kind": "Switch",
                "reason": "Missing channel",
                "line": "Switch testSwitch",
            }
        ],
        "recommended_missing": [],
    }

    diff_payload = [
        {"type": "removed", "line": "Old line", "orig_ln": 1},
        {"type": "added", "line": "New line", "curr_ln": 1},
        {"type": "unchanged", "line": "Keep line", "orig_ln": 2, "curr_ln": 2},
    ]

    def _fulfill(route, data, status=200):
        route.fulfill(
            status=status,
            content_type="application/json",
            body=json.dumps(data),
        )

    def handler(route, request):
        url = request.url
        method = request.method

        if url.endswith("/api/jobs"):
            return _fulfill(route, jobs)
        if re.search(r"/api/job/[^/]+$", url) and method == "GET":
            job = dict(jobs[0])
            job.setdefault("log", [])
            return _fulfill(route, job)
        if re.search(r"/api/job/[^/]+/file/diff", url):
            return _fulfill(route, diff_payload)
        if re.search(r"/api/job/[^/]+/diff", url):
            return _fulfill(route, {"items/knx.items": diff_payload})
        if re.search(r"/api/file/preview", url):
            if "completeness_report.json" in url:
                return _fulfill(route, {"content": json.dumps(report_payload)})
            if "job_id=" in url:
                return _fulfill(route, {"content": "New line\nKeep line\n", "size": 22})
            return _fulfill(route, {"content": "Old line\nKeep line\n", "size": 21})
        if re.search(r"/api/service/.*/status", url):
            return _fulfill(route, {"active": False, "status": "inactive"})
        if url.endswith("/api/version"):
            return _fulfill(route, {"commit_short": "abc123"})
        if url.endswith("/api/version/check"):
            return _fulfill(route, {"update_available": False})
        if url.endswith("/api/config"):
            return _fulfill(route, {})

        return _fulfill(route, {"error": f"unmocked {url}"}, status=404)

    page.route("**/api/**", handler)


@pytest.mark.ui
def test_preview_dialog_and_diff_mode(page: Page, flask_server):
    _setup_preview_routes(page)
    page.goto(flask_server)
    page.get_by_role("combobox", name="Sprache / Language").select_option("en")
    page.wait_for_function("window.refreshJobs !== undefined")

    expect(page.locator(".job-item")).to_have_count(1)
    page.locator(".job-item button:has-text('Details')").click()

    stats_table = page.locator("#stats .stats-table")
    expect(stats_table).to_be_visible()

    preview_button = page.locator(
        "#stats tr:has-text('items/knx.items') button:has-text('Preview')"
    )
    preview_button.click()

    dialog = page.locator("#filePreviewDialog[open]")
    expect(dialog).to_be_visible()
    expect(page.locator("#previewFileName")).to_contain_text("items/knx.items")
    expect(page.locator("#previewContent")).to_contain_text("New line")

    page.locator("#viewModeDiff").click()
    expect(page.locator("#diffLegend")).to_be_visible()
    expect(page.locator("#diffContent")).to_contain_text("New line")
    expect(page.locator("#diffContent .diff-line.added")).to_have_count(1)


@pytest.mark.ui
def test_expert_reports_panel(page: Page, flask_server):
    _setup_preview_routes(page)
    page.goto(flask_server)
    page.get_by_role("combobox", name="Sprache / Language").select_option("en")
    page.wait_for_function("window.refreshJobs !== undefined")

    expect(page.locator(".job-item")).to_have_count(1)
    page.locator(".job-item button:has-text('Details')").click()

    expert_toggle = page.locator("#expertToggle")
    expect(expert_toggle).to_be_visible()
    expert_toggle.check()

    panel = page.locator("#expertPanel")
    expect(panel).to_be_visible()
    expect(panel).to_contain_text("Expert Reports")
    expect(panel).to_contain_text("completeness_report.json")

    panel.locator("button:has-text('View')").first.click()
    expect(page.locator("#summaryDialog[open]")).to_be_visible()
    expect(page.locator("#summaryDialogContent")).to_contain_text("Missing required")


@pytest.mark.ui
def test_statistics_reports_and_file_preview_controls_follow_language(page: Page, flask_server):
    _setup_preview_routes(page)
    page.goto(flask_server)
    page.get_by_role("combobox", name="Sprache / Language").select_option("en")
    expect(page.locator(".job-item")).to_have_count(1)
    page.locator(".job-item button").first.click()

    headers = page.locator("#stats th")
    expect(headers).to_have_text(["File", "Before", "After", "Change", "Diff", "Action"])
    report_row = page.locator("#stats tr").filter(has_text="items/knx.items")
    expect(report_row.get_by_role("button")).to_have_text(["Preview"])

    page.get_by_role("combobox", name="Sprache / Language").select_option("de")
    expect(page.locator("#stats h3")).to_have_text("Erzeugte Dateien")
    expect(headers).to_have_text(["Datei", "Vorher", "Nachher", "Änderung", "Diff", "Aktion"])
    expect(report_row.get_by_role("button")).to_have_text(["Vorschau"])

    report_row.get_by_role("button", name="Vorschau").click()
    expect(page.locator("#previewContent")).to_contain_text("New line")
    expect(page.locator("#viewModeFinal")).to_have_text("Endansicht")
    page.get_by_role("combobox", name="Sprache / Language").select_option("en")
    expect(page.locator("#viewModeFinal")).to_have_text("Final View")
    expect(page.locator("#previewContent")).to_contain_text("New line")

    page.locator("#filePreviewDialog").evaluate("dialog => dialog.close()")
    page.locator("#expertToggle").check()
    page.locator("#expertPanel button", has_text="View").first.click()
    expect(page.locator("#summaryDialogContent")).to_contain_text("Required missing: 1")
    expect(page.locator("#summaryDialogContent")).to_contain_text("Missing required")
    page.get_by_role("combobox", name="Sprache / Language").select_option("de")
    expect(page.locator("#summaryDialogContent")).to_contain_text("Fehlende Pflichtangaben: 1")
    expect(page.locator("#summaryDialogContent")).to_contain_text("Fehlende Pflichtangaben")
    expect(page.locator("#summaryDialogContent")).to_contain_text("Switch testSwitch")


@pytest.mark.ui
def test_rollback_dialog_localizes_without_changing_backup_name(page: Page, flask_server):
    backup_name = "backup-ets-20261101.tar.gz"
    _setup_preview_routes(page, backups=[{"name": backup_name, "ts": "2026-11-01 12:00"}])
    page.goto(flask_server)
    expect(page.locator(".job-item")).to_have_count(1)
    page.locator(".job-item button", has_text="Wiederherstellen").click()

    expect(page.locator("#rollbackDialog")).to_be_visible()
    expect(page.locator("#rollbackDialog h2")).to_have_text("Aus Backup wiederherstellen")
    expect(page.locator("#backupSelect option")).to_have_text(f"{backup_name} (2026-11-01 12:00)")
    page.get_by_role("combobox", name="Sprache / Language").select_option("en")
    expect(page.locator("#rollbackDialog h2")).to_have_text("Rollback to Backup")
    expect(page.locator("#backupSelect")).to_have_value(backup_name)
