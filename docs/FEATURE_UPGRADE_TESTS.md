# FeatureUpgrade: Integrations- und Testbericht

- **Branch:** `developer/feature-upgrade`
- **Ausgangsbasis:** `main` (`f092abd`)
- **Prüfstand:** 23.10.2026
- **Umfang:** elf offene PRs #33, #35, #37, #39, #42–#48; #39 war ein Draft.
- **Benutzerübersicht:** [Änderungen und Bedienung](FEATURE_UPGRADE.md)

> **Betriebsgrenze:** Es wurde kein produktives Gerät angesprochen. Die Runtime-Migration besteht automatisierte Tests, aber es gab keine Probe mit einem Abbild einer realen Bestandsinstallation und keinen Wiederherstellungslauf. Deshalb ist der Branch kein freigegebenes Bestands-Upgrade.

## Aktueller Prüfstand

Die aktuelle Runde überarbeitet die GitHub-README und den Einstieg in die Anwenderanleitung, ergänzt eine Setup-Sperre für erkannte Bestandsinstallationen vor Systemänderungen, sperrt die `main`-Selbstaktualisierung für Vorschau-Branches und ersetzt die allgemeine Deploy-Bestätigung durch eine Dateiliste mit Diff und ausdrücklicher Freigabe. Neue Guardrail- und Browserprüfungen gehören zur Runde. Der Browserlauf erzeugt `test-results/feature-upgrade/deploy-review.png` für das [Screenshot-Artefakt](https://github.com/diddip21/knx_to_openhab/actions/runs/40032134387/artifacts/12535542421) (abrufbar bis 21.01.2027).

[GitHub Actions Run #522](https://github.com/diddip21/knx_to_openhab/actions/runs/40032134387) auf dem vollständigen Qualitätsstand `d1ac2f7` ist erfolgreich: **404 Core-Tests bestanden, 11 übersprungen** unter Python 3.12 und 3.13; **109 Browser-Tests bestanden, 2 übersprungen**; Formatierung, Importreihenfolge, Flake8 und Mypy bestanden. Lokal bestanden dieselben 404 Core-Tests; ein lokaler Chromium-Lauf war in dieser Umgebung nicht verfügbar. Eine reale Migration und Wiederherstellung einer repräsentativen Bestandsanlage ist weiterhin nicht durchgeführt, daher gibt es keine Freigabe für produktive Bestandsanlagen.

Auch [Run #524](https://github.com/diddip21/knx_to_openhab/actions/runs/40032779556) auf `1c24902` ist vollständig erfolgreich. Bei der anschließenden Repository-Bereinigung bestanden lokal erneut 404 Core-Tests (11 übersprungen), Black, isort, Flake8, JavaScript- und Shell-Syntaxprüfungen sowie alle lokalen Dokumentationslinks. Der CI-Lauf des Bereinigungs-Commits wird separat geprüft.

### Noch erforderliche Freigabeprobe auf einer isolierten Kopie

- Vorher: Version, Konfiguration, Benutzerzugang, Bind-Adresse/Port, Jobs, Staging, Backups, Dienste und manuell gepflegte openHAB-Dateien auf einer **nicht produktiven** Kopie erfassen; separat eine vollständige wiederherstellbare Gerätesicherung anlegen.
- Migration: nur auf dieser Kopie die ausdrücklich als Labortest gekennzeichnete Setup-Option verwenden. Danach Werte, Dateirechte, Dienststarts, Fernzugriff und vorhandene Job-/Backupdaten mit dem Vorher-Stand vergleichen. Jede unerwartete Änderung blockiert die Freigabe.
- Anwendung: das gleiche ETS-Testprojekt im bisherigen Standardformat verarbeiten; Diff prüfen, Deploy bestätigen und verwaltete Dateien kontrollieren. Optionales YAML auf einer passenden openHAB-5.2-Testinstanz laden. Manuelle Dateien müssen erhalten bleiben.
- Wiederherstellung: sowohl einen Deploy-Rollback als auch die **vollständige Rückkehr zum vorherigen Installationsstand** aus der Gerätesicherung durchführen und Daten, Zugriff und Dienste erneut vergleichen. Ein reiner Test der App-Rollback-Taste ersetzt diesen Schritt nicht.
- Nachweis: Befehle, Testumgebung, Vorher-/Nachher-Ergebnisse, Abweichungen und Freigabeentscheidung hier ergänzen. Bis alle Schritte bestanden sind, keine produktive Upgrade-Anleitung veröffentlichen und `main` nicht mit diesem Branch zusammenführen.

## Ergebnis

Dieser Branch sammelt die Änderungen zur gemeinsamen Prüfung. `main` bleibt unverändert. Die Quell-PRs bleiben auf GitHub offen; ihre Änderungen sind in diesem Integrationsbranch enthalten. Der Branch ist kein Release und wurde nicht auf ein echtes openHAB-System ausgerollt.

Der Diff enthält nach der Bereinigung 65 neu hinzugefügte Repository-Dateien: 31 Testdateien, 13 Installer-/Systemhelfer, 9 Programmdateien, 9 Screenshot-Dateien und 3 technische Dokumente. Diese Liste beschreibt den Quellcode und die Prüfbelege im GitHub-Repository; sie entspricht nicht der Anzahl neuer openHAB-Ausgabedateien. Die normale `legacy`-Ausgabe bleibt der Standard.

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

Die aufgelösten Merge-Commits und die zusätzlichen Integrationskorrekturen sind Teil des Branches. Die Prüfung des Remote-Branches bestätigt, dass alle elf PR-Head-Commits enthalten sind, der Git-Index keine ungelösten Konflikte enthält und keine Konfliktmarker in den Dateien verblieben sind.

## Prüfmethoden und Grenzen

Der [gemeinsame CI-Lauf #522](https://github.com/diddip21/knx_to_openhab/actions/runs/40032134387) prüfte den integrierten Code mit Core- und Integrationstests auf Python 3.12/3.13, Black, isort, Flake8, Mypy und 109 erfolgreichen Browser-Tests in Chromium. Die früheren PR-Einzelergebnisse sind keine Gesamtabnahme. Nach diesem Lauf wurden ausschließlich Dokumentation und die hier erläuterten Bildbelege bereinigt.

Der [Anwendervergleich](FEATURE_UPGRADE.md) verlinkt die eingecheckten Screenshots und kennzeichnet Bereiche ohne authentische Vorher-Aufnahme. Der neue Deploy-Dialog wurde im [CI-Screenshot-Artefakt](https://github.com/diddip21/knx_to_openhab/actions/runs/40032134387/artifacts/12535542421) aufgenommen. Die Bilder nutzen synthetische Testdaten; ein Video wurde nicht erzeugt.

**Nicht nachgewiesen:** Ein realer YAML-Ladevorgang auf openHAB 5.2, ein echtes APT-Update sowie die Migration und vollständige Wiederherstellung einer repräsentativen Bestandsinstallation. Dafür gilt die [isolierte Freigabeprobe](#noch-erforderliche-freigabeprobe-auf-einer-isolierten-kopie). Ohne diesen Nachweis ist der Branch kein produktives Upgrade.
