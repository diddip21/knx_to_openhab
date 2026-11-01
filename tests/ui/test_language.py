"""Browser tests for language selection and translation behavior."""

import json
import re
from pathlib import Path

import pytest
from playwright.sync_api import Page, Route, expect

LANGUAGE_KEY = "knx_to_openhab.locale"


def _stub_background_apis(
    page: Page,
    *,
    jobs=None,
    upload_error=None,
    config_payload=None,
    config_save_error=None,
    package_task=None,
    package_operation_error=None,
    gateway_state=None,
    gateway_action_error=None,
    project_preview=None,
    project_preview_error=None,
):
    """Keep unrelated host/API work outside language selector tests."""

    def api_response(route):
        url = route.request.url.split("?", 1)[0]
        method = route.request.method
        if url.endswith("/api/upload") and upload_error is not None:
            route.fulfill(
                status=400,
                content_type="application/json",
                body=json.dumps({"error": upload_error}),
            )
            return
        if url.endswith("/api/project/preview") and method == "POST":
            if project_preview_error is not None:
                route.fulfill(
                    status=400,
                    content_type="application/json",
                    body=json.dumps({"error": project_preview_error}),
                )
            else:
                route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps(project_preview or {"metadata": {}, "buildings": []}),
                )
            return
        if url.endswith("/api/gateway/ip") and method == "POST" and gateway_action_error:
            route.fulfill(
                status=400,
                content_type="application/json",
                body=json.dumps({"error": gateway_action_error}),
            )
            return
        if "/api/service/updates/" in url and method == "POST":
            route.fulfill(
                status=409 if package_operation_error else 200,
                content_type="application/json",
                body=json.dumps(
                    {"error": package_operation_error}
                    if package_operation_error
                    else {"success": True}
                ),
            )
            return
        if url.endswith("/api/config") and method == "POST":
            route.fulfill(
                status=500 if config_save_error else 200,
                content_type="application/json",
                body=json.dumps(
                    {"error": config_save_error} if config_save_error else {"ok": True}
                ),
            )
            return
        if url.endswith("/api/jobs"):
            data = jobs if jobs is not None else []
        elif url.endswith("/api/config"):
            data = config_payload or {}
        elif url.endswith("/api/version"):
            data = {"commit_short": "test"}
        elif url.endswith("/api/version/check"):
            data = {"update_available": False}
        elif url.endswith("/api/service/updates/status"):
            data = package_task or {"action": None, "state": "idle", "message": ""}
        elif url.endswith("/api/gateway/state"):
            data = gateway_state or {}
        elif url.endswith("/version"):
            data = {
                "installed": None,
                "candidate": None,
                "supported": False,
                "update_available": False,
                "message": "APT package is not installed on this host.",
            }
        else:
            data = {
                "active": False,
                "status": "inactive",
                "uptime_str": None,
                "last_run_str": None,
            }
        route.fulfill(status=200, content_type="application/json", body=json.dumps(data))

    page.route("**/api/**", api_response)


@pytest.mark.ui
def test_fresh_browser_defaults_to_german(page: Page, flask_server):
    _stub_background_apis(page)
    page.goto(flask_server, wait_until="domcontentloaded")

    language_select = page.get_by_role("combobox", name="Sprache / Language")
    expect(language_select).to_have_value("de")
    expect(page.locator("html")).to_have_attribute("lang", "de")


@pytest.mark.ui
def test_unsupported_stored_locale_falls_back_to_german(page: Page, flask_server):
    _stub_background_apis(page)
    page.add_init_script(f"window.localStorage.setItem('{LANGUAGE_KEY}', 'fr')")
    page.goto(flask_server, wait_until="domcontentloaded")

    expect(page.get_by_role("combobox", name="Sprache / Language")).to_have_value("de")
    expect(page.locator("html")).to_have_attribute("lang", "de")


@pytest.mark.ui
def test_language_selection_persists_after_reload_and_new_page(page: Page, flask_server):
    _stub_background_apis(page)
    page.goto(flask_server, wait_until="domcontentloaded")
    language_select = page.get_by_role("combobox", name="Sprache / Language")
    language_select.select_option("en")
    expect(page.locator("html")).to_have_attribute("lang", "en")

    page.reload()
    expect(page.get_by_role("combobox", name="Sprache / Language")).to_have_value("en")
    expect(page.locator("html")).to_have_attribute("lang", "en")

    reopened_page = page.context.new_page()
    _stub_background_apis(reopened_page)
    reopened_page.goto(flask_server, wait_until="domcontentloaded")
    expect(reopened_page.get_by_role("combobox", name="Sprache / Language")).to_have_value("en")
    expect(reopened_page.locator("html")).to_have_attribute("lang", "en")


@pytest.mark.ui
def test_translation_catalogs_match_and_unknown_locale_falls_back(page: Page, flask_server):
    _stub_background_apis(page)
    page.goto(flask_server, wait_until="domcontentloaded")

    catalog_keys = page.evaluate("""() => ({
          de: window.I18N ? Object.keys(window.I18N.catalogs.de).sort() : null,
          en: window.I18N ? Object.keys(window.I18N.catalogs.en).sort() : null,
          references: Array.from(document.querySelectorAll('*')).flatMap(element =>
            Array.from(element.attributes)
              .filter(attribute => attribute.name === 'data-i18n' ||
                (attribute.name.startsWith('data-i18n-') && attribute.name !== 'data-i18n-params'))
              .map(attribute => attribute.value)
          ),
          unknownLocale: window.I18N ? window.I18N.setLanguage('fr') : null,
          resolvedLocale: window.I18N ? window.I18N.getLanguage() : null,
          documentLocale: document.documentElement.lang
        })""")

    assert catalog_keys["de"] is not None
    assert catalog_keys["en"] is not None

    assert catalog_keys["de"] == catalog_keys["en"]
    assert set(catalog_keys["references"]) <= set(catalog_keys["de"])
    assert catalog_keys["unknownLocale"] == "de"
    assert catalog_keys["resolvedLocale"] == "de"
    assert catalog_keys["documentLocale"] == "de"
    assert page.evaluate("window.I18N.t('settings.floorAsIsHelp')") == (
        "Den Etagennamen genau wie in ETS definiert verwenden."
    )


@pytest.mark.ui
def test_gateway_controls_and_live_state_follow_selected_language(page: Page, flask_server):
    _stub_background_apis(
        page,
        gateway_state={
            "things_format": "dsl",
            "managed_path": "openhab/things/knx.things",
            "gateway_ip": "192.0.2.42",
            "gateway_mode": "TUNNEL",
            "detected_gateway_ip": "198.51.100.10",
            "reset_available": True,
            "undo_available": True,
        },
    )
    page.goto(flask_server, wait_until="domcontentloaded")
    expect(page.locator("#configStatus")).to_contain_text("Konfiguration geladen")
    page.locator("#settings-section .card-header").click()
    page.get_by_role("button", name="Geräte").click()

    expect(
        page.get_by_role("button", name="IP in die aktive OpenHAB-Datei übernehmen")
    ).to_be_enabled()
    german_state = page.locator("#gateway-file-state")
    expect(german_state).to_contain_text("Verwaltete DSL-Datei openhab/things/knx.things")
    expect(german_state).to_contain_text("192.0.2.42")
    expect(german_state).to_contain_text("198.51.100.10")
    page.get_by_role("button", name="Allgemein").click()
    page.locator("#conf-output-format").select_option("yaml")
    german_warning = page.locator("#gateway-format-warning")
    expect(german_warning).to_contain_text("OpenHAB-Version konnte nicht ermittelt werden")

    page.get_by_role("combobox", name="Sprache / Language").select_option("en")

    expect(page.locator("#gateway-format-warning")).to_contain_text(
        "OpenHAB version could not be determined"
    )
    page.get_by_role("button", name="Devices").click()
    expect(page.get_by_role("button", name="Apply IP to live OpenHAB file")).to_be_enabled()
    english_state = page.locator("#gateway-file-state")
    expect(english_state).to_contain_text("Managed DSL file openhab/things/knx.things")
    expect(english_state).to_contain_text("192.0.2.42")
    expect(english_state).to_contain_text("198.51.100.10")


@pytest.mark.ui
def test_gateway_action_error_follows_selected_language(page: Page, flask_server):
    _stub_background_apis(
        page,
        gateway_action_error="Invalid IP address: invalid",
        gateway_state={
            "things_format": "dsl",
            "managed_path": "openhab/things/knx.things",
            "reset_available": True,
            "undo_available": True,
        },
    )
    page.goto(flask_server, wait_until="domcontentloaded")
    expect(page.locator("#configStatus")).to_contain_text("Konfiguration geladen")
    page.locator("#settings-section .card-header").click()
    page.get_by_role("button", name="Geräte").click()
    page.locator("#conf-gateway-ip").fill("192.0.2.55")
    page.once("dialog", lambda dialog: dialog.accept())
    page.get_by_role("button", name="IP in die aktive OpenHAB-Datei übernehmen").click()

    status = page.locator("#gateway-action-status")
    expect(status).to_contain_text("Ungültige IP-Adresse: invalid")

    page.get_by_role("combobox", name="Sprache / Language").select_option("en")
    expect(status).to_contain_text("Invalid IP address: invalid")


@pytest.mark.ui
def test_language_selector_exposes_german_and_english(page: Page, flask_server):
    _stub_background_apis(page)
    page.goto(flask_server, wait_until="domcontentloaded")

    language_select = page.get_by_role("combobox", name="Sprache / Language")
    expect(language_select.locator("option")).to_have_count(2)
    expect(language_select.locator("option[value='de']")).to_have_text("Deutsch")
    expect(language_select.locator("option[value='en']")).to_have_text("English")


@pytest.mark.ui
def test_dashboard_static_copy_switches_between_german_and_english(page: Page, flask_server):
    _stub_background_apis(page)
    page.goto(flask_server, wait_until="domcontentloaded")

    expect(page.locator("#upload-section h2 span")).to_have_text("KNX-Projekt hochladen")
    expect(page.locator("#settings-section h2 span")).to_have_text("Konfigurationseinstellungen")
    expect(page.locator("#service-section h2 span")).to_have_text("Dienste")

    page.get_by_role("combobox", name="Sprache / Language").select_option("en")
    expect(page.locator("#upload-section h2 span")).to_have_text("Upload KNX Project")
    expect(page.locator("#settings-section h2 span")).to_have_text("Configuration Settings")
    expect(page.locator("#service-section h2 span")).to_have_text("Services")
    expect(page.locator("#settings-content .tab-btn").first).to_have_text("General")


@pytest.mark.ui
def test_login_copy_switches_between_german_and_english(page: Page, auth_preview_server):
    page.goto(f"{auth_preview_server}/login", wait_until="domcontentloaded")

    expect(page.locator(".login-card h1")).to_have_text("Anmelden")
    expect(page.locator(".login-intro")).to_have_text(
        "Geben Sie Ihre Web-UI-Zugangsdaten ein, um fortzufahren."
    )

    page.get_by_role("combobox", name="Sprache / Language").select_option("en")
    expect(page.locator(".login-card h1")).to_have_text("Sign in")
    expect(page.locator(".login-intro")).to_have_text("Enter your Web UI credentials to continue.")
    expect(page.locator("label[for='username']")).to_have_text("Username")

    references = page.evaluate(
        """() => Array.from(document.querySelectorAll('*')).flatMap(element =>
      Array.from(element.attributes)
        .filter(attribute => attribute.name === 'data-i18n' ||
          (attribute.name.startsWith('data-i18n-') && attribute.name !== 'data-i18n-params'))
        .map(attribute => attribute.value)
    )"""
    )
    keys = page.evaluate("Object.keys(window.I18N.catalogs.en)")
    assert set(references) <= set(keys)


@pytest.mark.ui
def test_known_job_messages_translate_and_keep_dynamic_values(page: Page, auth_preview_server):
    page.goto(f"{auth_preview_server}/login", wait_until="domcontentloaded")

    translations = page.evaluate("""() => {
      const backup = 'backup created: knx-job-42-20261101.tar.gz'
      const taggedBackup = '[12:34:56] [BACKUP] backup created: knx-job-42-20261101.tar.gz'
      const unknown = '[ERROR] ETS parser detail: Raum Küche / GA 1/2/3'
      window.I18N.setLanguage('en')
      const english = window.I18N.translateMessage(backup)
      const taggedEnglish = window.I18N.translateMessage(taggedBackup)
      const unknownEnglish = window.I18N.translateMessage(unknown)
      window.I18N.setLanguage('de')
      return {
        english,
        taggedEnglish,
        german: window.I18N.translateMessage(backup),
        taggedGerman: window.I18N.translateMessage(taggedBackup),
        staged: window.I18N.translateMessage('completed (staged) - ready to deploy'),
        failedStatus: window.I18N.translateMessage('[STATUS] failed'),
        unknownEnglish,
        unknownGerman: window.I18N.translateMessage(unknown)
      }
    }""")

    assert translations["english"] == "Backup created: knx-job-42-20261101.tar.gz"
    assert translations["taggedEnglish"] == (
        "[12:34:56] [Backup] Backup created: knx-job-42-20261101.tar.gz"
    )
    assert translations["german"] == "Sicherung erstellt: knx-job-42-20261101.tar.gz"
    assert translations["taggedGerman"] == (
        "[12:34:56] [Sicherung] Sicherung erstellt: knx-job-42-20261101.tar.gz"
    )
    assert (
        translations["staged"] == "Abgeschlossen (zwischengespeichert) – bereit zur Bereitstellung"
    )
    assert translations["failedStatus"] == "[Status] Fehlgeschlagen"
    assert translations["unknownEnglish"] == "[ERROR] ETS parser detail: Raum Küche / GA 1/2/3"
    assert translations["unknownGerman"] == "[ERROR] ETS parser detail: Raum Küche / GA 1/2/3"


@pytest.mark.ui
def test_job_list_actions_and_status_follow_selected_language(page: Page, flask_server):
    _stub_background_apis(
        page,
        jobs=[
            {
                "id": "job-language-42",
                "name": "Wohnzimmer KNX",
                "status": "completed",
                "created": 1700000000,
                "staged": True,
                "deployed": False,
                "backups": [{"name": "backup.tar.gz", "ts": "2026-01-01"}],
            }
        ],
    )
    page.goto(flask_server, wait_until="domcontentloaded")

    job = page.locator(".job-item")
    expect(job.locator(".job-status")).to_have_text("Abgeschlossen")
    expect(job.get_by_role("button")).to_have_text(
        ["Details", "Struktur", "Änderungen", "Bereitstellen", "Wiederherstellen", "Löschen"]
    )

    page.get_by_role("combobox", name="Sprache / Language").select_option("en")
    expect(job.locator(".job-status")).to_have_text("Completed")
    expect(job.get_by_role("button")).to_have_text(
        ["Details", "Structure", "Diff", "Deploy", "Rollback", "Delete"]
    )


@pytest.mark.ui
def test_job_dates_follow_selected_language(page: Page, flask_server):
    timestamp = 1704196800
    job_data = {
        "id": "job-date-locale",
        "name": "Date Locale Project",
        "status": "completed",
        "created": timestamp,
        "backups": [],
    }
    _stub_background_apis(page, jobs=[job_data])
    page.goto(flask_server, wait_until="domcontentloaded")
    expected = page.evaluate(
        "timestamp => ({de: new Date(timestamp * 1000).toLocaleString('de-DE'), "
        "en: new Date(timestamp * 1000).toLocaleString('en-US')})",
        timestamp,
    )
    assert expected["de"] != expected["en"]
    expect(page.locator(".job-date")).to_have_text(expected["de"])
    page.evaluate("job => { currentJobData = job; renderJobDetails(job) }", job_data)
    expect(page.locator("#jobDetail")).to_contain_text(expected["de"])

    page.get_by_role("combobox", name="Sprache / Language").select_option("en")
    expect(page.locator(".job-date")).to_have_text(expected["en"])
    expect(page.locator("#jobDetail")).to_contain_text(expected["en"])


@pytest.mark.ui
def test_empty_diff_dialog_copy_refreshes_after_language_change(page: Page, flask_server):
    _stub_background_apis(page)
    page.route(
        "**/api/job/diff-locale/diff",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body="{}",
        ),
    )
    page.goto(flask_server, wait_until="domcontentloaded")
    page.evaluate("showDiff('diff-locale')")
    expect(page.locator("#filePreviewDialog[open]")).to_be_visible()
    expect(page.locator("#previewFileName")).to_have_text("Diff für Auftrag diff-locale")
    expect(page.locator("#diffContent")).to_have_text("Keine Unterschiede vorhanden.")

    page.evaluate("window.I18N.setLanguage('en')")
    expect(page.locator("#previewFileName")).to_have_text("Diff for job diff-locale")
    expect(page.locator("#diffContent")).to_have_text("No differences available.")


@pytest.mark.ui
def test_empty_file_preview_diff_refreshes_after_language_change(page: Page, flask_server):
    _stub_background_apis(page)
    page.route(
        "**/api/file/preview**",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                {"path": "openhab/things/empty.things", "content": "Thing example {}", "size": 16}
            ),
        ),
    )
    page.route(
        "**/api/job/preview-empty-diff/file/diff**",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body="[]",
        ),
    )
    page.goto(flask_server, wait_until="domcontentloaded")
    page.evaluate("currentJobId = 'preview-empty-diff'")
    page.evaluate("previewFile('openhab/things/empty.things')")
    expect(page.locator("#filePreviewDialog[open]")).to_be_visible()
    page.locator("#viewModeDiff").click()
    expect(page.locator("#diffContent")).to_contain_text("(leerer Diff)")

    page.evaluate("window.I18N.setLanguage('en')")
    expect(page.locator("#diffContent")).to_contain_text("(empty diff)")


@pytest.mark.ui
def test_open_update_dialog_dates_follow_selected_language(page: Page, flask_server):
    timestamp = "2024-01-02T12:00:00Z"
    update_data = {
        "current_commit": "abc123",
        "current_message": "Current version",
        "current_date": timestamp,
        "latest_commit": "def456",
        "latest_message": "New version",
        "latest_author": "KNX Maintainer",
        "latest_date": timestamp,
    }
    _stub_background_apis(page)
    page.goto(flask_server, wait_until="domcontentloaded")
    expected = page.evaluate(
        "timestamp => ({de: new Date(timestamp).toLocaleString('de-DE'), "
        "en: new Date(timestamp).toLocaleString('en-US')})",
        timestamp,
    )
    assert expected["de"] != expected["en"]
    page.evaluate(
        "data => { latestVersionData = data; showUpdateDialog(data) }",
        update_data,
    )
    expect(page.locator("#dialogCurrentDate")).to_have_text(expected["de"])
    expect(page.locator("#dialogLatestDate")).to_have_text(expected["de"])

    page.evaluate("window.I18N.setLanguage('en')")
    expect(page.locator("#dialogCurrentDate")).to_have_text(expected["en"])
    expect(page.locator("#dialogLatestDate")).to_have_text(expected["en"])
    page.locator("#updateDialog").evaluate("dialog => dialog.close()")


@pytest.mark.ui
def test_deploy_action_stays_disabled_during_language_change(page: Page, flask_server):
    pending_deploy = []
    jobs = [
        {
            "id": "job-deploying",
            "name": "Demo Project",
            "status": "completed",
            "created": 1700000000,
            "staged": True,
            "deployed": False,
            "backups": [],
        }
    ]
    _stub_background_apis(
        page,
        jobs=jobs,
    )

    def hold_deploy(route):
        pending_deploy.append(route)

    page.route("**/api/job/job-deploying/deploy", hold_deploy)
    page.goto(flask_server, wait_until="domcontentloaded")
    job = page.locator(".job-item")
    page.on("dialog", lambda dialog: dialog.accept())
    with page.expect_request("**/api/job/job-deploying/deploy"):
        job.get_by_role("button", name="Bereitstellen").click()

    page.get_by_role("combobox", name="Sprache / Language").select_option("en")
    deploy_button = page.locator(".job-item button[onclick=\"deployJob('job-deploying')\"]")
    expect(deploy_button).to_have_text("Processing…")
    expect(deploy_button).to_be_disabled()

    jobs[0]["deployed"] = True
    pending_deploy[0].fulfill(
        status=200,
        content_type="application/json",
        body=json.dumps({"success": True, "message": "OK"}),
    )
    expect(page.locator(".job-item").get_by_role("button", name="Deploy")).to_have_count(0)


@pytest.mark.ui
def test_stale_job_refresh_cannot_restore_deploy_after_deployment(page: Page, flask_server):
    pending_deploy: list[Route] = []
    pending_job_refresh: list[Route] = []
    jobs = [
        {
            "id": "job-stale-refresh",
            "name": "Demo Project",
            "status": "completed",
            "created": 1700000000,
            "staged": True,
            "deployed": False,
            "backups": [],
        }
    ]
    stale_job_payload = json.dumps([{**jobs[0], "name": "Stale response"}])
    _stub_background_apis(page, jobs=jobs)
    page.route("**/api/job/job-stale-refresh/deploy", lambda route: pending_deploy.append(route))
    page.add_init_script("window.setInterval = () => 0")
    page.goto(flask_server, wait_until="domcontentloaded")
    expect(page.locator(".job-item")).to_contain_text("Demo Project")
    page.evaluate("""() => {
      const originalRefreshJobs = window.refreshJobs
      window.completedJobRefreshes = 0
      window.refreshJobs = async (...args) => {
        const result = await originalRefreshJobs(...args)
        window.completedJobRefreshes += 1
        return result
      }
    }""")
    page.on("dialog", lambda dialog: dialog.accept())

    with page.expect_request("**/api/job/job-stale-refresh/deploy"):
        page.locator(".job-item").get_by_role("button", name="Bereitstellen").click()

    def delay_first_job_refresh(route):
        if not pending_job_refresh:
            pending_job_refresh.append(route)
            return
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(jobs),
        )

    page.route("**/api/jobs", delay_first_job_refresh)
    with page.expect_request("**/api/jobs"):
        page.get_by_role("combobox", name="Sprache / Language").select_option("en")

    jobs[0]["deployed"] = True
    pending_deploy[0].fulfill(
        status=200,
        content_type="application/json",
        body=json.dumps({"success": True, "message": "OK"}),
    )
    page.wait_for_function("window.completedJobRefreshes === 1")
    expect(page.locator(".job-item").get_by_role("button", name="Deploy")).to_have_count(0)

    with page.expect_response(lambda response: response.url.endswith("/api/jobs")):
        pending_job_refresh[0].fulfill(
            status=200,
            content_type="application/json",
            body=stale_job_payload,
        )
    page.wait_for_function("window.completedJobRefreshes === 2")
    expect(page.locator(".job-item .job-name")).to_have_text("Demo Project")
    expect(page.locator(".job-item").get_by_role("button", name="Deploy")).to_have_count(0)


@pytest.mark.ui
def test_package_operation_action_follows_selected_language(page: Page, flask_server):
    _stub_background_apis(
        page,
        package_task={
            "action": "refresh",
            "state": "completed",
            "message": "Package lists refreshed.",
        },
    )
    page.goto(flask_server, wait_until="domcontentloaded")
    expect(page.locator("#packageOperationStatus")).to_have_text(
        "Paketlisten aktualisieren: Paketlisten aktualisiert."
    )

    page.get_by_role("combobox", name="Sprache / Language").select_option("en")
    expect(page.locator("#packageOperationStatus")).to_have_text(
        "Refresh package lists: Package lists refreshed."
    )


@pytest.mark.ui
@pytest.mark.parametrize(
    ("error", "expected_de", "expected_en"),
    [
        (
            "Update helper is not installed. Run sudo bash installer/setup.sh once.",
            "Update-Hilfsprogramm ist nicht installiert. Führen Sie einmal sudo bash installer/setup.sh aus.",
            "Update helper is not installed. Run sudo bash installer/setup.sh once.",
        ),
        (
            "No APT update is available for this package.",
            "Für dieses Paket ist kein APT-Update verfügbar.",
            "No APT update is available for this package.",
        ),
    ],
)
def test_package_operation_errors_follow_selected_language(
    page: Page, flask_server, error: str, expected_de: str, expected_en: str
):
    _stub_background_apis(page, package_operation_error=error)
    page.goto(flask_server, wait_until="domcontentloaded")
    page.evaluate("startPackageOperation('openhab')")
    status = page.locator("#packageOperationStatus")
    expect(status).to_have_text(expected_de)

    page.get_by_role("combobox", name="Sprache / Language").select_option("en")
    expect(status).to_have_text(expected_en)


@pytest.mark.ui
def test_package_action_error_overrides_non_idle_task_after_locale_change(page: Page, flask_server):
    _stub_background_apis(
        page,
        package_operation_error="No APT update is available for this package.",
        package_task={"action": "refresh", "state": "running", "message": "Starting APT…"},
    )
    page.goto(flask_server, wait_until="domcontentloaded")
    page.wait_for_function("currentPackageTask && currentPackageTask.state === 'running'")
    page.evaluate("startPackageOperation('openhab')")
    status = page.locator("#packageOperationStatus")
    expect(status).to_have_text("Für dieses Paket ist kein APT-Update verfügbar.")

    page.get_by_role("combobox", name="Sprache / Language").select_option("en")
    expect(status).to_have_text("No APT update is available for this package.")
    with page.expect_response(
        lambda response: response.url.endswith("/api/service/updates/status")
    ):
        page.evaluate("startPackageOperationPolling()")
    expect(status).to_have_text("No APT update is available for this package.")


@pytest.mark.ui
def test_package_action_error_survives_failed_status_poll(page: Page, flask_server):
    error = "No APT update is available for this package."
    _stub_background_apis(page, package_operation_error=error)
    page.route(
        "**/api/service/updates/status",
        lambda route: route.fulfill(
            status=503,
            content_type="application/json",
            body=json.dumps({"error": "temporary status failure"}),
        ),
    )
    page.goto(flask_server, wait_until="domcontentloaded")
    page.evaluate("startPackageOperation('openhab')")

    status = page.locator("#packageOperationStatus")
    expect(status).to_have_text("Für dieses Paket ist kein APT-Update verfügbar.")
    with page.expect_response(
        lambda response: response.url.endswith("/api/service/updates/status")
    ):
        page.evaluate("startPackageOperationPolling()")
    expect(status).to_have_text("Für dieses Paket ist kein APT-Update verfügbar.")

    page.get_by_role("combobox", name="Sprache / Language").select_option("en")
    expect(status).to_have_text(error)


@pytest.mark.ui
def test_live_log_timestamps_follow_selected_language(page: Page, flask_server):
    timestamp = 1704196800000
    event = {
        "type": "info",
        "level": "info",
        "message": "live log locale marker",
        "timestamp": timestamp,
    }
    _stub_background_apis(page)
    page.route(
        "**/api/job/log-locale/events",
        lambda route: route.fulfill(
            status=200,
            content_type="text/event-stream",
            body=f"data: {json.dumps(event)}\n\n",
        ),
    )
    page.goto(flask_server, wait_until="domcontentloaded")
    page.evaluate("startEvents('log-locale')")

    expected = page.evaluate(
        "timestamp => ({de: new Date(timestamp).toLocaleTimeString('de-DE'), "
        "en: new Date(timestamp).toLocaleTimeString('en-US')})",
        timestamp,
    )
    assert expected["de"] != expected["en"]
    log = page.locator("#log")
    expect(log).to_contain_text(f"[{expected['de']}] [INFO] live log locale marker")

    page.get_by_role("combobox", name="Sprache / Language").select_option("en")
    expect(log).to_contain_text(f"[{expected['en']}] [INFO] live log locale marker")


@pytest.mark.ui
def test_locally_generated_structure_errors_follow_selected_language(page: Page, flask_server):
    _stub_background_apis(page)
    page.route(
        "**/api/job/missing-job",
        lambda route: route.fulfill(
            status=503,
            content_type="application/json",
            body=json.dumps({"error": "temporary service detail"}),
        ),
    )
    page.goto(flask_server, wait_until="domcontentloaded")
    page.evaluate("loadStructureFromJob('missing-job')")
    expect(page.locator("#status")).to_have_text(
        "✗ Auftragsstatus konnte nicht abgerufen werden (HTTP 503)."
    )

    page.get_by_role("combobox", name="Sprache / Language").select_option("en")
    expect(page.locator("#status")).to_have_text("✗ Failed to retrieve job status (HTTP 503).")

    timeout_messages = page.evaluate("""() => {
      window.I18N.setLanguage('de')
      const german = window.I18N.t('structure.timeout', { seconds: 30 })
      window.I18N.setLanguage('en')
      return { german, english: window.I18N.t('structure.timeout', { seconds: 30 }) }
    }""")
    assert timeout_messages == {
        "german": "✗ Auftrag wurde nicht innerhalb von 30 Sekunden abgeschlossen.",
        "english": "✗ Job did not complete within 30 seconds.",
    }


@pytest.mark.ui
def test_upload_failure_is_localized_without_translating_server_detail(page: Page, flask_server):
    detail = "Parser rejected Raum Küche at GA 1/2/3"
    _stub_background_apis(page, upload_error=detail)
    page.goto(flask_server, wait_until="domcontentloaded")
    page.get_by_role("combobox", name="Sprache / Language").select_option("en")
    page.locator("#fileInput").set_input_files(
        {"name": "project.knxproj", "mimeType": "application/octet-stream", "buffer": b"invalid"}
    )
    page.locator("#uploadForm button[type='submit']").click()
    expect(page.locator("#status")).to_have_text(f"Upload error: {detail}")

    page.get_by_role("combobox", name="Sprache / Language").select_option("de")
    expect(page.locator("#status")).to_have_text(f"Upload-Fehler: {detail}")


@pytest.mark.ui
def test_settings_feedback_localizes_without_resetting_edited_values_or_file(
    page: Page, flask_server
):
    _stub_background_apis(
        page,
        config_payload={
            "output_format": "yaml",
            "yaml_path": "openhab/yaml/knx.yaml",
            "general": {"unknown_floorname": "Unbekannte Etage"},
        },
    )
    page.goto(flask_server, wait_until="domcontentloaded")
    expect(page.locator("#conf-yaml-path")).to_have_value("openhab/yaml/knx.yaml", timeout=5000)
    expect(page.locator("#configStatus")).to_have_text("✓ Konfiguration geladen")
    page.locator("#settings-section .card-header").click()
    page.locator("#conf-yaml-path").fill("openhab/yaml/edited.yaml")
    page.locator("#fileInput").set_input_files(
        {
            "name": "mein-projekt.knxproj",
            "mimeType": "application/octet-stream",
            "buffer": b"project",
        }
    )

    page.get_by_role("combobox", name="Sprache / Language").select_option("en")
    expect(page.locator("#conf-yaml-path")).to_have_value("openhab/yaml/edited.yaml")
    expect(page.locator("#fileInput")).to_have_value(re.compile("mein-projekt.knxproj"))
    expect(page.locator("#settings-content")).to_be_visible()
    expect(page.locator("#configStatus")).to_have_text("✓ Configuration loaded")

    page.locator("#settings-content .settings-actions .btn-primary").click()
    expect(page.locator("#configStatus")).to_have_text("✓ Configuration saved")
    page.get_by_role("combobox", name="Sprache / Language").select_option("de")
    expect(page.locator("#configStatus")).to_have_text("✓ Konfiguration gespeichert")
    expect(page.locator("#conf-yaml-path")).to_have_value("openhab/yaml/edited.yaml")
    expect(page.locator("#fileInput")).to_have_value(re.compile("mein-projekt.knxproj"))


@pytest.mark.ui
def test_failed_config_save_follows_selected_language(page: Page, flask_server):
    _stub_background_apis(page, config_save_error="temporary save failure")
    page.goto(flask_server, wait_until="domcontentloaded")
    expect(page.locator("#configStatus")).to_have_text("✓ Konfiguration geladen")
    page.locator("#settings-section .card-header").click()

    with page.expect_response(
        lambda response: response.url.endswith("/api/config") and response.request.method == "POST"
    ) as save_response:
        page.locator("#settings-content .settings-actions .btn-primary").click()
    assert save_response.value.status == 500
    status = page.locator("#configStatus")
    expect(status).to_have_text("Konfiguration konnte nicht gespeichert werden")

    page.get_by_role("combobox", name="Sprache / Language").select_option("en")
    expect(status).to_have_text("Failed to save configuration")


@pytest.mark.ui
def test_reprocess_feedback_follows_selected_language_when_no_job_is_selected(
    page: Page, flask_server
):
    _stub_background_apis(page)
    dialogs = []

    def accept_dialog(dialog):
        dialogs.append(dialog.message)
        dialog.accept()

    page.on("dialog", accept_dialog)
    page.goto(flask_server, wait_until="domcontentloaded")
    expect(page.locator("#configStatus")).to_have_text("✓ Konfiguration geladen", timeout=5000)
    page.locator("#settings-section .card-header").click()
    page.locator("#settings-content .btn-outline").click()
    expect(page.locator("#configStatus")).to_have_text("✓ Konfiguration gespeichert")
    assert dialogs[-1] == (
        "Kein Auftrag zum erneuten Verarbeiten ausgewählt. Bitte wählen Sie zuerst einen Auftrag aus."
    )

    page.get_by_role("combobox", name="Sprache / Language").select_option("en")
    page.locator("#settings-content .btn-outline").click()
    expect(page.locator("#configStatus")).to_have_text("✓ Configuration saved")
    assert dialogs[-1] == "No job selected to reprocess. Please select a job first."


@pytest.mark.ui
def test_project_preview_localizes_labels_and_errors_but_keeps_project_data(
    page: Page, flask_server
):
    payload = {
        "metadata": {
            "project_name": "Haus Müller",
            "gateway_ip": "192.168.1.45",
            "total_addresses": 3,
            "homekit_enabled": True,
            "alexa_enabled": False,
            "unknown_items": [{"name": "Deckenlicht Küche", "address": "1/2/3"}],
        },
        "buildings": [],
    }
    _stub_background_apis(page, project_preview=payload)
    page.goto(flask_server, wait_until="domcontentloaded")
    page.locator("#fileInput").set_input_files(
        {"name": "haus.knxproj", "mimeType": "application/octet-stream", "buffer": b"project"}
    )
    page.get_by_role("button", name="Strukturvorschau").click()

    metadata = page.locator("#previewMetadata")
    expect(metadata).to_contain_text("Projekt:")
    expect(metadata).to_contain_text("Haus Müller")
    expect(page.locator("#status")).to_have_text("✓ Projektstruktur geladen")

    page.get_by_role("combobox", name="Sprache / Language").select_option("en")
    expect(metadata).to_contain_text("Project:")
    expect(metadata).to_contain_text("Haus Müller")
    expect(metadata).to_contain_text("Unknown items:")
    expect(page.locator("#status")).to_have_text("✓ Project structure loaded")
    expect(page.locator("#fileInput")).to_have_value(re.compile("haus.knxproj"))


@pytest.mark.ui
def test_project_preview_error_is_localized_and_keeps_parser_detail(page: Page, flask_server):
    detail = "ETS parser rejected Raum Küche"
    _stub_background_apis(page, project_preview_error=detail)
    page.goto(flask_server, wait_until="domcontentloaded")
    page.locator("#fileInput").set_input_files(
        {"name": "haus.knxproj", "mimeType": "application/octet-stream", "buffer": b"project"}
    )
    page.get_by_role("button", name="Strukturvorschau").click()
    expect(page.locator("#status")).to_have_text(f"✗ Fehler: {detail}")
    page.get_by_role("combobox", name="Sprache / Language").select_option("en")
    expect(page.locator("#status")).to_have_text(f"✗ Error: {detail}")


@pytest.mark.ui
def test_login_error_follows_selected_language(page: Page, auth_preview_server):
    page.goto(f"{auth_preview_server}/login", wait_until="domcontentloaded")
    page.get_by_label("Benutzername").fill("operator")
    page.get_by_label("Passwort").fill("incorrect-password")
    page.get_by_role("button", name="Anmelden").click()
    expect(page.locator(".login-error")).to_have_text("Benutzername oder Passwort ist falsch.")

    page.get_by_role("combobox", name="Sprache / Language").select_option("en")
    expect(page.locator(".login-error")).to_have_text("Username or password is incorrect.")


@pytest.mark.ui
def test_capture_german_and_english_dashboard_screenshots(page: Page, flask_server):
    _stub_background_apis(
        page,
        jobs=[
            {
                "id": "demo-job-56",
                "name": "Demo KNX Project",
                "status": "completed",
                "created": 1793552400,
                "staged": True,
                "deployed": False,
                "backups": [],
            }
        ],
    )
    page.goto(flask_server, wait_until="domcontentloaded")
    expect(page.locator(".job-item")).to_contain_text("Demo KNX Project")
    expect(page.locator("#servicesList .service-item")).to_have_count(2, timeout=10000)
    screenshot_dir = Path(__file__).resolve().parents[2] / "docs" / "screenshots"
    screenshot_dir.mkdir(parents=True, exist_ok=True)

    page.get_by_role("combobox", name="Sprache / Language").select_option("de")
    expect(page.locator("#upload-section h2 span")).to_have_text("KNX-Projekt hochladen")
    expect(page.locator("#servicesList .service-item").first).to_contain_text("Inaktiv")
    expect(page.locator("#servicesList .service-item").first).to_contain_text(
        "APT-Paket ist auf diesem Host nicht installiert."
    )
    page.screenshot(path=str(screenshot_dir / "issue-56-language-de.png"), full_page=True)

    page.get_by_role("combobox", name="Sprache / Language").select_option("en")
    expect(page.locator("#upload-section h2 span")).to_have_text("Upload KNX Project")
    expect(page.locator(".job-item")).to_contain_text("Demo KNX Project")
    expect(page.locator("#servicesList .service-item").first).to_contain_text("Inactive")
    expect(page.locator("#servicesList .service-item").first).to_contain_text(
        "APT package is not installed on this host."
    )
    page.screenshot(path=str(screenshot_dir / "issue-56-language-en.png"), full_page=True)
