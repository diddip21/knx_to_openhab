# FeatureUpgrade: Integrations- und Testbericht

**Branch:** `developer/feature-upgrade`  
**Ausgangsbasis:** `main` (`f092abd`)  
**Prüfstand:** 23.10.2026  
**Umfang:** alle elf zu diesem Zeitpunkt offenen PRs #33, #35, #37, #39, #42, #43, #44, #45, #46, #47 und #48. PR #39 ist ein Draft.  
**Benutzerübersicht:** [FeatureUpgrade: Änderungen und Bedienung](FEATURE_UPGRADE.md)

## Ergebnis

Dieser Branch sammelt die Änderungen zur gemeinsamen Prüfung. `main` bleibt unverändert. Die Quell-PRs bleiben auf GitHub offen; ihre Änderungen sind in diesem Integrationsbranch enthalten. Der Branch ist kein Release und wurde nicht auf ein echtes openHAB-System ausgerollt.

Der vollständige GitHub-Actions-Lauf für den finalen Branch wird nach Veröffentlichung des Branches dokumentiert. Bis dieser Lauf abgeschlossen ist, ist die gemeinsame Testprüfung als **ausstehend** zu behandeln. Die einzelnen PRs enthalten frühere, getrennte Testläufe; diese ersetzen den Test des integrierten Stands nicht.

## Eingeflossene PRs

| PR | Inhalt | Relevante Bereiche |
|---|---|---|
| [#33](https://github.com/diddip21/knx_to_openhab/pull/33) | KNX-Uploads, Archive, Vorschau und Projektpasswörter absichern | `web_ui/backend/upload_security.py`, `web_ui/backend/jobs.py`, Upload- und Vorschautests |
| [#35](https://github.com/diddip21/knx_to_openhab/pull/35) | Playwright-Regressionstests für Weboberfläche und Jobabläufe | `tests/ui/`, `.github/workflows/ci.yml` |
| [#37](https://github.com/diddip21/knx_to_openhab/pull/37) | Nicht ausgeführte, doppelte und veraltete Tests/Hilfsskripte entfernen | Test- und Generator-Dateien; keine Produktionslogik |
| [#39](https://github.com/diddip21/knx_to_openhab/pull/39) | Optionale native openHAB-5.2-YAML-Ausgabe | `openhab_yaml.py`, Generator, Konfiguration, UI, Migration/Deploy-Tests |
| [#42](https://github.com/diddip21/knx_to_openhab/pull/42) | Optionale Gateway-IP für KNX | Geräte-Einstellungen, Generator und Regressionstests |
| [#43](https://github.com/diddip21/knx_to_openhab/pull/43) | APT-Status und Einzelupdates für openHAB und evcc | Service-API, root-eigener Helper, UI und Tests |
| [#44](https://github.com/diddip21/knx_to_openhab/pull/44) | Pauschale Root-Rechte für Git/Systemd entfernen | Sudoers-Allowlist, Migration und Service-Manager |
| [#45](https://github.com/diddip21/knx_to_openhab/pull/45) | Deploy und Rollback auf verwaltete OpenHAB-Ausgaben begrenzen | `deploy_policy.py`, Jobs, Provisionierung und Berechtigungstests |
| [#46](https://github.com/diddip21/knx_to_openhab/pull/46) | Konfiguration, Laufzeitdaten und Sicherungen trennen und migrieren | `knxoh_paths.py`, Installer, Storage, Service- und Migrationstests |
| [#47](https://github.com/diddip21/knx_to_openhab/pull/47) | Festes Standardpasswort entfernen und Argon2id einführen | Authentifizierung, Setup, Secret-Migration und Passworttests |
| [#48](https://github.com/diddip21/knx_to_openhab/pull/48) | Sitzungen, CSRF-Schutz, Sperre bei Loginversuchen und localhost-Standard | Web-API, UI, Installer, Browser- und Sessiontests |

Die [vollständige Dateiliste und der gesamte Diff gegenüber `main`](https://github.com/diddip21/knx_to_openhab/compare/main...developer/feature-upgrade) zeigen auch jede entfernte und neu hinzugefügte Datei. Die Benutzerübersicht dokumentiert jede PR mit Wirkung und Bedienhinweisen; dieses Dokument ergänzt die technische Integration und Testnachweise.

## Merge-Konflikte und Integrationskorrekturen

Die folgenden fachlichen Konflikte wurden beim Zusammenführen aufgelöst:

| Dateien/Bereich | Auflösung |
|---|---|
| `config.json` (#39 / #42) | YAML-Ausgabepfade und Konfiguration für die Gateway-IP zusammengeführt; bestehende Felder beibehalten. |
| `web_ui/static/app.js` (#39 / #43) | Auswahl des Ausgabeformats und Bedienung der Paketupdates gemeinsam erhalten. |
| `installer/setup.sh`, `web_ui/backend/jobs.py` (#33 / #39 / #45) | Upload-Schutz, YAML-Staging und begrenzte Deploy-Policy zusammengeführt. |
| `web_ui/README.md`, `web_ui/backend/app.py` (#43 / #46) | Service-Updates, Importe und zentrale Laufzeitpfade gemeinsam erhalten. |
| `tests/ui/conftest.py`, `tests/ui/test_settings_config.py` (#42 / #47) | Authentifizierungs-Testaufbau mit Gateway-IP-Regressionsfällen kombiniert. |
| `.github/workflows/ci.yml`, `web_ui/backend/app.py`, `web_ui/static/app.js` (#43 / #48) | Screenshot-Artefakte auch nach erfolgreichem CI-Lauf hochladen; Sessions/CSRF mit Service-Update- und Upload-Flows integriert. |

Zusätzlich wurde bei der integrierten Prüfung ein Sicherheitsproblem an der Grenze von #39 und #45 behoben: Das Umschalten zwischen Text- und YAML-Ausgabe muss alte, generierte Modell-Dateien entfernen können, obwohl der Webdienst keine allgemeinen Schreibrechte auf OpenHAB-Verzeichnisse besitzt. Dafür provisioniert Setup eine root-eigene Manifestdatei und einen separaten, root-eigenen Helper außerhalb des App-Verzeichnisses. Der Helper verwendet nur die Standardbibliothek, akzeptiert ausschließlich die beiden Formatnamen und entfernt nur zuvor provisionierte, inaktive Ausgabedateien. Sudoers erlaubt genau diese Aufrufe. Tests prüfen unter anderem nicht verwaltete Dateien, Symlinks und Wiederherstellung nach einem Teilfehler.

Die aufgelösten Merge-Commits und diese Korrektur sind Teil des Branches. Beim Abschluss der Prüfung werden außerdem das Fehlen ungelöster Git-Konflikte und nicht aufgelöster Konfliktmarker festgehalten.

## Testumfang und Status

Der integrierte CI-Workflow führt aus:

- Core-, Unit- und Integrationstests mit Coverage auf Python 3.12 und 3.13.
- Format-, Importreihenfolge-, Flake8- und Mypy-Prüfungen.
- Playwright-UI-Tests mit Chromium.
- Upload der UI-Screenshots und Playwright-Berichte als GitHub-Actions-Artefakt, auch wenn ein UI-Test fehlschlägt.

| Prüfung | Ergebnis auf dem finalen Integrationsbranch |
|---|---|
| GitHub Actions: Core Tests, Python 3.12 und 3.13 | Ausstehend; nach dem Branch-Push aktualisieren. |
| GitHub Actions: Lint und Mypy | Ausstehend; nach dem Branch-Push aktualisieren. |
| GitHub Actions: Playwright UI und Screenshot-Artefakt | Ausstehend; nach dem Branch-Push aktualisieren. |
| Lokale Core-Suite | **400 bestanden, 11 übersprungen** unter Python 3.12.14 mit dem CI-Testbefehl. |
| Lokales Black / isort / Flake8 | Bestanden nach der Formatkorrektur. |
| Lokales Mypy | Der Standardlauf endet in dieser Containerumgebung mit einem internen psutil-Fehler (`NoSuchProcess`, Runner-PID nicht sichtbar). Der Fallback-Lauf mit `--no-native-parser` meldet keine Fehler in 95 Dateien. Der Mypy-Gate auf GitHub Actions bleibt maßgeblich. |
| Lokale Playwright-UI-Suite | Nicht ausgeführt: der lokale Chromium-Download lieferte ein ungültiges, leeres Archiv. Der vollständige Browserlauf läuft auf dem GitHub-Actions-Runner. |
| Reales openHAB-5.2-YAML-Smoke-Load | Nicht ausgeführt; erfordert eine passende laufende openHAB-Instanz. |
| Echtes APT-Paketupdate | Nicht ausgeführt; es wurde kein Zielgerät verändert. |
| Upgrade-/Datenmigration einer repräsentativen Installation | Nicht ausgeführt; die Migration ist durch automatisierte Tests abgedeckt, aber noch nicht auf einem Bestandsgerät erprobt. |

Die getrennten CI-Ergebnisse aus den Quell-PRs sind im jeweiligen PR verlinkt und nicht als Gesamtergebnis dieses FeatureUpgrade-Branches zu verstehen.

## Screenshot- und Vorher-/Nachher-Nachweis

Die Screenshots für Login, authentifiziertes Dashboard und Sitzungsablauf liegen unter [`docs/screenshots/feature-upgrade/`](screenshots/feature-upgrade/). Einstellungen und Beispielausgaben für YAML, Gateway-IP und Paketupdates liegen unter [`docs/screenshots/`](screenshots/). Die Benutzerübersicht stellt sie jeweils neben den Vorher-Zustand.

Die Bilder enthalten synthetische Testdaten. Es liegt kein Video vor. Für interne Änderungen an Uploadvalidierung, Dateirechten, Passwortablage, Laufzeitmigration und Testinfrastruktur gibt es keinen eigenständigen UI-Bildschirm; ihre Änderung und Prüfung ist oben je PR und im Quellcode/Testbericht beschrieben. Für YAML, Gateway-IP und Paketupdates existieren keine authentischen Screenshots der alten `main`-Oberfläche; diese Einschränkung ist in der Benutzerübersicht kenntlich gemacht.

## Interne Dokumentation

- `AGENTS.md`: Regeln für künftige PR-Stapel, Branch-Schutz, Konfliktprotokoll und Dokumentation.
- `docs/DEVELOPER_GUIDE.md`: Architektur, zentrale Runtime-Pfade, Branch-/Integrationsablauf und Sicherheitsinvarianten.
- `docs/PRODUCTION_GUIDE.md`: Installation, Rechte, Secrets, Migration, Paketupdates und Netzwerkzugriff.
- `docs/USER_GUIDE.md`: Bedienung der neuen Anwenderfunktionen.
- `docs/SECURITY_UPLOAD.md`: Upload- und Archivverarbeitung.
- `installer/README.md` und `web_ui/README.md`: Installer-, Laufzeit- und Web-UI-Hinweise.

