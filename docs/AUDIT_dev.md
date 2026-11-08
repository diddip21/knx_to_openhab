# Audit von `dev` vor der Bereinigung

Stand: 2026-11-08, `origin/dev` bei `42d380b159e86bf075318846b6457de854b4c8c0`. Arbeitsbranch: `cleanup/dev-audit`. Das lokale `dev` enthält sechs zusätzliche, nicht nach `origin/dev` übertragene Commits; sie gehören nicht zu diesem Audit oder einem PR nach `dev`. Die Inventur und Dateientscheidungen unten dokumentieren den **unveränderten Ausgangsstand (Phase 1 und 2)**. Bis zur Maintainer-Freigabe wurden keine Dateien gelöscht und weder Generator noch Konfiguration verändert.

## Methode und Grenzen

`git ls-tree -r --name-only origin/dev` und `git ls-files` ergeben 232 versionierte Dateien. Der Dateibestand ist in der Tabelle unten vollständig und einzeln erfasst. Referenzen wurden mit `rg`, AST-Importanalyse, Skript-/Workflow-Aufrufsuche und gezielten Quelltextprüfungen untersucht. Statische Suche beweist keine Abwesenheit externer Aufrufer; insbesondere veröffentlichte Links und PR-Beschreibungen sind außerhalb des Git-Baums. Dateien mit diesem Restzweifel bleiben vorerst erhalten. `vulture`, `ruff`, `gitleaks`, `trufflehog`, `shellcheck`, `bash` und Docker sind auf dem Prüfhost nicht verfügbar. Der verlangte Befehl `run_secret_scanning` wird durch keine verfügbare Schnittstelle angeboten; das unten beschriebene Musterscanning ist kein gleichwertiger Ersatz. Linux-/systemd-Installation wurde hier nicht ausgeführt.

## Tatsächlicher Datenfluss

1. Die CLI `knxproject_to_openhab.py:739-800` liest mit `--readDump` JSON oder parst ETS mit `XKNXProj`; ohne `--file_path` nutzt sie optional Tk. `create_building()`, `get_addresses()` und `put_addresses_in_building()` bauen die Struktur. Die Web-UI nimmt Uploads über `web_ui/backend/app.py` entgegen, prüft sie in `upload_security.py` und startet Verarbeitung/Staging mit `web_ui/backend/jobs.py`.
2. `knxproject_to_openhab.py:787-796` setzt Modulzustand in `ets_to_openhab` und ruft dessen `main()` auf. `ets_to_openhab.py:1127-1146` erzeugt Legacy-Text und optional ein YAML-Modell. `config.py:21-25,211` liest die Generator-Konfiguration beim Import. Im installierten Betrieb liegt sie laut `knxoh_paths.py:79-80` unter `/var/lib/knx_to_openhab/generator.json`; die lokale Voreinstellung ist `config.json`.
3. Bei `output_format=legacy` werden `things.template`, `items.template`, `sitemap.template` in `ets_to_openhab.py:964-1015` gelesen. Bei `yaml` validiert und rendert `openhab_yaml.py:168,288-296` das Modell, aufgerufen über `ets_to_openhab.py:1050-1059`. Die jeweils andere Modellform wird in vorhandenen Dateien geleert (`ets_to_openhab.py:1018-1065`). `influxdb.persist` und `fenster.rules` werden bei beiden Formaten textuell erzeugt (`ets_to_openhab.py:1067-1124`). Reports sind bedingt; `partial_report.json` entsteht nur bei Einträgen (`ets_to_openhab.py:942-945`), `completeness_report.json` im Jobpfad (`jobs.py:1044,1201-1242`).
4. `jobs.py` verwaltet Stage, Voll-Backup und Deploy/Rollback (`jobs.py:830-835`, `deploy_policy.py`). `install.sh:631,648-655` wählt einen Release-Tag und startet `installer/setup.sh`; `setup.sh:221-296` installiert App, Laufzeitdaten, Dienstdateien, Hilfsprogramme und Rechte. `update.sh` ist der vom Web-Updater gestartete Release-Wechsel (`web_ui/backend/updater.py:288-306`). `uninstall.sh` entfernt standardmäßig die Anwendung und lässt externe Nutzdaten zurück (`uninstall.sh:13-19,313-316`).

## Einstiegspunkte und Importgraph

| Einstieg | Rolle und Abhängigkeit | Urteil |
| --- | --- | --- |
| `knxproject_to_openhab.py` | CLI und in-process Job-Aufruf → `config`, `ets_to_openhab`, `xknxproject` (`knxproject_to_openhab.py:11-15,739-800`; `jobs.py:142-151`) | aktiv |
| `ets_to_openhab.py` | Generator → `config`, `ets_helpers`, `utils`, `openhab_yaml` (`ets_to_openhab.py:9-23,1127-1146`) | aktiv |
| `openhab_yaml.py` | nur YAML-Renderer/Validator; ersetzt Legacy-Templates nicht (`ets_to_openhab.py:11-22,1050-1061`) | aktiv |
| `web_ui/backend/__main__.py`, `app.py`, `jobs.py` | Webstart → App/Jobmanager → Generator; Service- und Gateway-Module sind über relative Imports eingebunden (`__main__.py:6-15`, `app.py:53-60`, `jobs.py:21-39`) | aktiv |
| `install.sh`, `installer/setup.sh`, `update.sh`, `uninstall.sh`, `fix_permissions.sh` | Installation, Update, Deinstallation und Reparatur (`install.sh:648-655`, `updater.py:306`, `fix_permissions.sh:53-68`) | aktiv |
| `installer/*.py`, `installer/*.sh`, systemd/sudoers | Aufrufe durch `setup.sh:228-296`, `fix_permissions.sh:53-68`, Unit-Dateien und Tests; die bloße Abwesenheit eines Python-Imports ist hier kein Totbeleg | aktiv |
| `scripts/build_release.py` | Release-Workflow (`.github/workflows/release.yml:32`) | aktiv |
| `scripts/generate_golden_files.py`, `scripts/regenerate_golden.py` | verschiedene Golden-Workflows (`docs/DEVELOPER_GUIDE.md:319-320`, `tests/README.md:111`) | aktiv |
| `scripts/dev-*.sh`, `scripts/dev-*.ps1`, `scripts/verify-setup.*` | lokal dokumentierte Entwicklerbefehle (`docs/DEVELOPER_GUIDE.md:21-47,145-150`) | aktiv, nicht im Produktionspfad |

Die AST-Analyse fand für alle Python-Produktionsmodule entweder einen Import, einen Skript-/Service-Aufruf oder einen dokumentierten Einstieg. Eine textuelle Symbolsuche fand **einen** Kandidaten für wirklich unbenutzte Implementierung: `AuthRateLimiter` ist nur bei seiner Definition in `web_ui/backend/auth.py:80` vorhanden; Login-Limits laufen über `session_store.py:135-172` und `app.py:430`. Kein Modul wurde allein wegen fehlenden Imports zum Löschen freigegeben. `flake8 --isolated --select=F401,F841` meldet `scripts/generate_golden_files.py:15` (`os`), `jobs.py:10` (`subprocess`), `service_manager.py:79-80` (`time`, `datetime`, `timedelta`), `storage.py:241` und `updater.py:356` (unbenutzte `e`). Das reguläre `flake8 .` verdeckt diese Funde durch `.flake8:7-17` und endet erfolgreich.

## Konfiguration, Templates und Abhängigkeiten

Alle 15 Top-Level-Keys aus `config.json` sind hier nach tatsächlichem Leseweg erfasst:

| Key | Leseweg | Befund |
| --- | --- | --- |
| `datapoint_mappings` | `config.py:226`; `ets_to_openhab.py:647` | dynamische DPT-Iteration; Einzeleinträge nicht wegen fehlender Literalreferenz löschen |
| `datapoint_types` | `utils.py:14` | dynamischer Schlüsselzugriff |
| `defines` | `ets_to_openhab.py:428,502,572,617,651,754` | aktiv |
| `devices` | `knxproject_to_openhab.py:661,676` | Gateway-Erkennung/Override |
| `fenster_path` | `ets_to_openhab.py:1116` | Fensterregel-Ausgabe |
| `general` | `knxproject_to_openhab.py:24-25,369-370`; `ets_to_openhab.py:266,292` | aktiv |
| `influx_path` | `ets_to_openhab.py:1085-1087` | Persistenz-Ausgabe |
| `items_path` | `ets_to_openhab.py:994-996` | Legacy-Ausgabe |
| `output_format` | `ets_to_openhab.py:1044-1065` | Formatwahl |
| `regexpattern` | `knxproject_to_openhab.py:20-22`; `ets_to_openhab.py:27-28` | aktiv |
| `sitemaps_path` | `ets_to_openhab.py:1007-1009` | Legacy-Ausgabe |
| `sitemap_label` | `ets_to_openhab.py:311`; `config.py:207` | YAML/Default |
| `things_path` | `ets_to_openhab.py:980-982` | Legacy-Ausgabe |
| `transform_dir_path` | `config.py:153,162-200` | nur Pfadnormalisierung nachgewiesen |
| `yaml_path` | `ets_to_openhab.py:1053-1054` | YAML-Ausgabe |

Die Web-Laufzeitkonfiguration ist getrennt: `web_ui/backend/config.json:2-19` und `web_ui/backend/storage.py:17-55` definieren Pfade, Bind-Adresse/Port, Auth, Retention und den Web-Auto-Place-Default. `knxoh_paths.py:79-80` löst die installierten Speicherorte auf. Das Generator-Schema ist `web_ui/backend/config_schema.json:3-15`; `web_ui/backend/app.py:1234-1237` stellt es der UI bereit. Die Map-Einträge unter `datapoint_mappings`, `datapoint_types` und `defines` werden über Werte/Typen statt feste Literalnamen ausgewählt (`ets_to_openhab.py:647-652`, `utils.py:14`); ein einzelner „ungenutzter“ DPT-Eintrag ist aus dem Importgraphen deshalb nicht beweisbar.

| Befund | Beleg | Bewertung |
| --- | --- | --- |
| Generator-`general.auto_place_unknown` ist `true`, Web-UI-Defaults `false` | `config.json:480`; `web_ui/backend/config.json:18`; `web_ui/backend/storage.py:31`; `knxproject_to_openhab.py:369-370` | Verschiedene Einstiegspfade haben verschiedene Defaults. Wegen Ausgabekompatibilität nicht stillschweigend angleichen; Doku muss beide Wege erklären. |
| `output_format=legacy` und Pfade für Items, Things, Sitemap, Influx, Fensterregel und YAML sind aktiv | `config.json:473,489-503`; `ets_to_openhab.py:1034-1124` | behalten. |
| `defines`, `regexpattern`, `datapoint_mappings`, `datapoint_types`, `devices`, `general` sind aktive Gruppen | `knxproject_to_openhab.py:20-25,658-684`; `ets_to_openhab.py:428,502,572,617,647-652,754`; `utils.py:14` | behalten; Einträge werden teils dynamisch iteriert. Einzelne fehlende Literal-Treffer sind kein Löschbeleg. |
| `transform_dir_path` wird normalisiert, aber nicht für Ausgabe gelesen | `config.json:502`; `config.py:146-154`; keine weiteren Treffer in Produktionscode | möglicher Alt-Key; Kompatibilitätsfrage, nicht löschen. |
| `openhab_path`, `target_user`, `target_group`, `special_char_map` werden durch `config.py` ergänzt | `config.py:202-224`; `ets_to_openhab.py:423,954` | nicht als fehlende JSON-Keys deuten. |
| `web_ui/backend/config_schema.json` beschreibt Generator-Einstellungen; `web_ui/backend/config.json` enthält Web-Laufzeitdefaults | `config_schema.json:3-15`; `web_ui/backend/storage.py:17-35` | gleichnamige Config-Dateien haben verschiedene Zwecke. |
| `pytest-dependency` steht in Produktionsanforderungen; im Repo keine Marker/Imports; `PyYAML` steht in Basis und Dev | `requirements.txt:7-8`; `requirements-dev.txt:17`; Suchlauf `rg 'pytest.mark.dependency|pytest_dependency' tests` ohne Treffer | Bereinigungskandidat, zunächst Abhängigkeits-/CI-Prüfung; keine neue Abhängigkeit. |
| `selenium`, `pylint`, `ipython`, `ipdb`, `pytest-flask`, `pytest-mock`, `pytest-xdist` sind in Dev-Requirements, ohne explizite Repo-Imports oder passende Fixture-Nutzung | `requirements-dev.txt:7-30`; Suchlauf über `tests scripts web_ui installer .github` ohne Treffer | möglicher Überhang; Plugin-Verwendung und Maintainer-Workflow vor Entfernung prüfen. |
| `Dockerfile.test` nutzt Python 3.11 und installiert weder `pytest-playwright` noch `pytest-timeout`, obwohl `pytest.ini` ihre Optionen bzw. Timeout nutzt | `Dockerfile.test:4,24-35`; `pytest.ini:25-35`; `.github/workflows/ci.yml:24,44-46` | dokumentierten Testcontainer auf 3.12/CI-Pfad bringen oder als nicht unterstützten Weg kennzeichnen. |
| `pyproject.toml`/CI zielen auf Python 3.12; Installer-Preflight akzeptiert 3.11+ | `pyproject.toml:4-7,22`; `.github/workflows/ci.yml:24`; `install.sh:425-447` | Ziel/Test- und Mindestversion explizit unterscheiden. |

## Abweichende oder unzureichende Doku-Aussagen (Ist → Soll)

1. `AGENTS.md:20-25` schreibt `export_output()` `openhab_yaml.py` zu; sie liegt in `ets_to_openhab.py:1034`. Datenfluss korrigieren.
2. `AGENTS.md:32-45` und `web_ui/README.md:20-21` nennen veraltete Zeilenzahlen; etwa `app.py` umfasst auf diesem Stand mehr als 1.500 statt 1.071 Zeilen. Flüchtige Zähler entfernen.
3. `AGENTS.md:53` beschreibt nur `E203/W503`; `.flake8:3,7-17` ignoriert zusätzlich `E501` und mehrere Dateien-spezifische F-Codes. Exakt dokumentieren oder Ignore-Liste gezielt abbauen.
4. `AGENTS.md:65`, `.github/copilot-instructions.md:49`, `docs/DEVELOPER_GUIDE.md:282-287`, `tests/README.md:54-57` behaupten, `pytest -q` schließe UI-Tests aus. `pytest.ini:5-17,22-35` setzt keinen Ausschluss; CI verwendet ausdrücklich `-m 'not ui' --ignore=tests/ui` (`.github/workflows/ci.yml:50`). Befehle und Aussage angleichen.
5. `docs/DEVELOPER_GUIDE.md:300-304`, `AGENTS.md:76` und `CONTRIBUTING.md:94-96` verlangen für UI-Tests einen separat gestarteten Server oder `-o addopts=`. `tests/ui/conftest.py:63-65,135-195` startet einen eigenen Flask-Prozess auf Port 8085 (oder `UI_BASE_URL`); CI ruft UI-Tests ohne `-o addopts=` auf (`ci.yml:137`). Anleitung aktualisieren.
6. `docs/USER_GUIDE.md:96-98` nennt `false` als allgemeinen Auto-Place-Default. CLI-Generator verwendet `true` (`config.json:480`), Web-UI `false` (`web_ui/backend/storage.py:31`). Beide Fälle angeben.
7. `docs/USER_GUIDE.md:35-37` nennt `.json` bei `--file_path` ohne unmittelbare Einschränkung; `knxproject_to_openhab.py:761-775` erkennt JSON automatisch nur nach dem Dateidialog, bei explizitem Pfad ist `--readDump` erforderlich. Beispiel ergänzen.
8. `README.md:95-103` listet YAML, Legacy und Persistence, aber keine `fenster.rules`; `ets_to_openhab.py:1095-1124` erzeugt sie. Dateiliste und Bedingtheit der Reports präzisieren (`README.md:109-111`; `ets_to_openhab.py:942-945`; `jobs.py:1044`).
9. `docs/PRODUCTION_GUIDE.md:134-139` behauptet, der Standard-Uninstaller lösche Service-Account und Backups. `uninstall.sh:13-19,313-316` tut dies nur mit `--purge`; bei piped/noninteraktivem Aufruf ist `--yes` erforderlich (`uninstall.sh:271-274`). `README.md:130-133` enthält denselben nicht copy-paste-fähigen Pipe-Aufruf. Sichere, genaue Befehle dokumentieren.
10. `installer/README.md:223` verlinkt `../DEVELOPMENT.md`, das nicht existiert. Auf `../docs/DEVELOPER_GUIDE.md` verweisen.
11. `docs/SECURITY_UPLOAD.md:28` behauptet, `max_upload_size_bytes` liege in `config.json`; `app.py:139` liest die Web-Konfiguration, die `storage.py:33-35` lädt. `docs/SECURITY_UPLOAD.md:69-81` nennt diese später richtig. Widerspruch beheben.
12. `CHANGELOG.md:5-7` enthält nur `[Unreleased]`; `VERSION:1` lautet `0.1.0`. `git ls-remote --tags origin` lieferte keinen Tag. Damit ist noch keine datierte Veröffentlichung belegbar; die Audit-Änderung gehört zunächst unter `[Unreleased]`. Datierte Notizen erst bei einem tatsächlichen Tag gemäß `docs/RELEASING.md:15-18` anlegen.
13. `docs/REPO_CLEANUP_INVENTORY.md:3,29-33` ist als historischer `main`-Schnappschuss formuliert und enthält mittlerweile veraltete PR-/Issue-Stände. Als Archiv kennzeichnen oder in diesen Audit integrieren; keine alten Status als aktuellen Stand darstellen.

Die Prüfung aller Markdown-Links auf relative Zielpfade fand 24 Ziele und genau den fehlenden Link unter Punkt 10. Externe HTTP-Links und Anker wurden dabei nicht online geprüft.

## Top 10 nach Priorität

1. Sicherheitsprüfung der realen ETS-Testdatei und Freigabe ihrer Veröffentlichung (`tests/fixtures/Charne.knxproj`, siehe unten).
2. Falsche Deinstallationsaussage und nicht ausführbarer Pipe-Befehl (`docs/PRODUCTION_GUIDE.md:134-139`, `uninstall.sh:271-274`).
3. Widersprüchlicher Auto-Place-Default (`config.json:480`, `storage.py:31`, `docs/USER_GUIDE.md:97`).
4. Falsche pytest-Standardanleitung (`pytest.ini:5-35`, `docs/DEVELOPER_GUIDE.md:282-287`).
5. Falsche JSON-CLI-Anleitung (`docs/USER_GUIDE.md:35-37`, `knxproject_to_openhab.py:761-775`).
6. Falsche Architekturzuordnung von YAML/Export (`AGENTS.md:20-25`, `ets_to_openhab.py:1034-1065`).
7. Testcontainer weicht von CI und pytest-Plugins ab (`Dockerfile.test:4,24-35`, `pytest.ini:25-35`).
8. Defekter Entwickler-Link (`installer/README.md:223`).
9. Historische Implementierungspläne gelangen in Quell-Releases (`docs/superpowers/**`, `scripts/build_release.py:77-92`).
10. Nicht dokumentierte Ignore-Lücken und isoliert gefundene unbenutzte Symbole/Imports (`.gitignore`, `.flake8:7-17`, `auth.py:80`).

## Tests, Hygiene und Sicherheit vor Bereinigung

Auf Windows/Python 3.12.14: `pytest -q` stoppt schon bei der Sammlung, weil `tests/test_uninstall_modes.py:2` `pty` und damit das Unix-Modul `termios` importiert. `flake8 .` hat Exitcode 0. `black --check .` meldete 112 unveränderte Dateien. `isort --check-only .` hatte Exitcode 0, warnte aber wegen Windows-Codepage bei mehreren Unicode-Testdateien; dieses Ergebnis ist daher nicht als vollständige Prüfung zu werten. `mypy . --no-incremental` meldete sieben Windows-spezifische `os`-Attributfehler. `pytest tests/integration/test_output_validation.py tests/test_openhab_yaml.py -q -o addopts=`: **32 bestanden, 2 übersprungen**. Der breite Windows-Teillauf auf `origin/dev` mit `--ignore=tests/test_uninstall_modes.py --ignore=tests/ui -q -o addopts= --tb=no` ergab **602 bestanden, 57 übersprungen, 62 fehlgeschlagen**; die Fehlerschwerpunkte sind POSIX-Dateimodi, `os.getuid`, Symlinks ohne Windows-Rechte und Bash-Installer-Tests. `pytest tests/ui/test_ui_smoke.py -q -o addopts= --tb=short` endet mit fünf Setup-Fehlern, weil die Chromium-Executable von Playwright auf dem Host fehlt. Eine volle Linux-/UI-/Shell-/Docker-Verifikation steht aus.

Ein erneuter isort-Lauf mit `python -X utf8 -m isort --check-only .` endete ohne Codepage-Warnungen mit Exitcode 0 (`Skipped 1 files`). Die Skip-Stellen umfassen Bash-abhängige Testmodule (`tests/test_installer_modes.py:12`, `tests/test_release_selection.py:11`), ausdrücklich POSIX-spezifische Fälle (`tests/test_deploy_policy.py:71-129`) und bedingte Generierungs-/Syntaxfälle (`tests/test_output_syntax_validation.py:313-525`). Vier `tests/test_output_config.py:276-297` überspringen ihre Tests ausdrücklich als komplexe Import-Fehlerfälle; diese Tests sind Kandidaten zur Nachbesserung, nicht zum Löschen. `git ls-files -ci --exclude-standard` lieferte keinen Treffer. Exakte SHA-256-Duplikate beschränken sich auf drei leere `__init__.py`-Paketdateien. Das größte versionierte Objekt ist die aktiv referenzierte `tests/fixtures/Charne.knxproj` mit 6.043.486 Byte (`tests/ui/test_upload_flow.py:9`; `docs/REPO_CLEANUP_INVENTORY.md:13-14`). JSON-Dumps, Mini-Fixture und Goldens werden in `tests/integration/test_output_validation.py:28,183-193` verwendet. Im Repository liegen keine versionierten `*.bak`, `*.old`, `*_copy`, `__pycache__` oder generierten `openhab/items|things|sitemaps`-Dateien. `.gitignore` deckt jedoch `.mypy_cache`, `.coverage*`, `htmlcov`, `private_persistence` (`ets_to_openhab.py:1068-1082`) und generische `*.bak`/`*.old` nicht ab.

Verfügbare Regex-Prüfung aller Textdateien und dekodierbaren ETS-ZIP-Inhalte auf gängige Token-/Key-Muster, E-Mail-Adressen und IPv4-Adressen: kein Treffer für die geprüften Token-/Private-Key-Muster; ein privater IPv4-Wert im realen `tests/fixtures/Charne.knxproj`, keine globale IPv4 und keine E-Mail in dieser Datei. Das ist ein möglicher Bezug zu einer echten Anlage. `tests/Charne.knxproj.json:4` nennt ein konkretes Projekt; die Goldens enthalten davon abgeleitete Item-Namen (`tests/fixtures/expected_output/Charne/knx.items:1`). In Tests kommen absichtlich synthetische Adressen vor, darunter `1.2.3.4` (`tests/test_web_ui_job_endpoints.py:225`). Ein professioneller Secret-Scanner und eine Freigabe/Anonymisierung der ETS-Daten sind noch nötig. Werte werden im Audit absichtlich nicht wiederholt.

## Verifikation nach der dokumentarischen Bereinigung

Geändert wurden ausschließlich Markdown-Dateien und `.gitignore`. `git diff --name-only origin/dev -- '*.py' '*.sh' '*.template' config.json web_ui/backend/config.json web_ui/backend/config_schema.json tests/fixtures/expected_output` liefert keinen Pfad. `scripts/regenerate_golden.py` erzeugte die drei Fälle Charne, UploadJson und Mini erneut; `git diff` der versionierten Goldens blieb leer. Das belegt bytegleiche Beispielausgaben für diese Fälle gegenüber `origin/dev`, nicht eine allgemeine Aussage über alle ETS-Projekte.

| Prüfung nach den Doku-Änderungen | Ergebnis |
| --- | --- |
| `pytest tests/integration/test_output_validation.py tests/test_openhab_yaml.py -q -o addopts=` | 32 bestanden, 2 übersprungen; identisch mit dem Ausgangsstand |
| `pytest -q --maxfail=1` | Abbruch bei `tests/test_uninstall_modes.py:2`, weil Windows `termios` fehlt; gleicher Ausgangsfehler |
| `black --check .` | Exit 0, 112 Dateien unverändert |
| `python -X utf8 -m isort --check-only .` | Exit 0, 1 Datei übersprungen |
| `flake8 .` | Exit 0 |
| `git diff --check` | Exit 0, nur Git-Hinweis auf künftige LF→CRLF-Normalisierung |
| Relative Markdown-Ziele einschließlich Anker | 36 geprüft, 0 defekt (lokales Prüfskript) |

Der vollständige CI-Kernbefehl, UI-Tests mit Chromium, `bash -n`, `shellcheck` und ein Docker-Build sind auf diesem Windows-Host nicht abschließend ausführbar. Der breite Windows-Teillauf und UI-Smoke-Fehler des Ausgangsstands stehen oben. Der Prüfhost bietet weder `bash`, `shellcheck`, Docker noch `run_secret_scanning`; der Regex-Scan ersetzt die geforderte Spezialprüfung nicht.

## Vorschlag für Phase 3 nach Freigabe

- Doku zuerst präzise korrigieren: README, CONTRIBUTING, AGENTS, Guides, Testanleitung und toten Link; Sprache der bestehenden englischen Doku beibehalten. Ausgabe-/Generatorcode nicht verändern.
- `.gitignore` gezielt um lokale Artefakte ergänzen; bereits versionierte Fixtures ausdrücklich erhalten.
- Niedrigrisiko-Codehygiene nur mit fokussierter Prüfung: die sieben isolierten F401/F841-Funde und ggf. die nur definierte Klasse `AuthRateLimiter`. Testcontainer und Requirements separat behandeln; die CI-Befehle vor Änderung als Referenz nehmen.
- Historische Pläne und alte Inventur nur nach Entscheidung über Archivwert entfernen/zusammenführen. Für jede Entfernung Suche erneut durchführen und Referenzen im gleichen Commit korrigieren.
- Vor/Nach-Ausgabe über die drei Golden-Fälle vergleichen; anschließend Kern-, relevante UI-, Lint-, Shell- und Link-Prüfungen sowie `git diff --check`. Keine Konvertierungsänderung und keine neuen Pakete.

## Rückfragen an Maintainer

1. Darf die `Charne`-ETS-Datei samt abgeleiteter Goldens öffentlich verbleiben, oder sollen diese Daten in einer gesonderten Folgearbeit anonymisiert/ersetzt werden? Ohne Ersatz brechen reale Upload- und Ausgabe-Tests; daher keine Löschung in diesem Cleanup.
2. Sollen `docs/superpowers/plans` und `docs/superpowers/specs` als historische Entwurfsakten im Repo bleiben? Sie werden nicht vom Produkt genutzt, sind aber untereinander und möglicherweise aus externen PRs verlinkt.
3. Wird `transform_dir_path` von externen Installationen als Konfigurationsvertrag genutzt? Im Repo ist außer der Normalisierung kein Ausgabeverbrauch nachweisbar.
4. Soll `Dockerfile.test` als unterstützter ARM-Testweg gepflegt werden? Dann müssen Python-/pytest-Umgebung mit CI abgeglichen werden.

## Vollständige Dateientscheidung

Die Spalte „Referenziert von“ nennt einen belegten internen Pfad oder den Discovery-Mechanismus. „Behalten“ bedeutet bei zweifelhaften, von außen eventuell referenzierten Artefakten ausdrücklich **keine** Bestätigung ihrer dauerhaften Notwendigkeit. Die Tabelle bewertet jeden der 232 versionierten Pfade einzeln. Ein Urteil „Löschen“ ist ein Vorschlag und **keine** bereits durchgeführte Aktion.

| Pfad | Zweck | Referenziert von | Urteil | Beleg | Risiko |
| --- | --- | --- | --- | --- | --- |
| `.flake8` | Lintregeln | .github/workflows/ci.yml:88 | AKTUALISIEREN | .github/workflows/ci.yml:88 | mittel |
| `.github/PULL_REQUEST_TEMPLATE.md` | PR-Vorlage | GitHub-Konvention für PR-Vorlagen | BEHALTEN | .github/PULL_REQUEST_TEMPLATE.md:1 | niedrig |
| `.github/copilot-instructions.md` | Agenten-Doku | GitHub-Konvention für Copilot | AKTUALISIEREN | .github/copilot-instructions.md:1 | niedrig |
| `.github/workflows/ci.yml` | CI-Pipeline | GitHub Actions bei Push/PR | BEHALTEN | .github/workflows/ci.yml:1-11 | mittel |
| `.github/workflows/release.yml` | Release-Pipeline | GitHub Actions bei Tag-Push | BEHALTEN | .github/workflows/release.yml:1-11 | mittel |
| `.gitignore` | Ignore-Regeln | tests/test_repository_hygiene.py:10 | AKTUALISIEREN | tests/test_repository_hygiene.py:10 | niedrig |
| `AGENTS.md` | Agentenhinweise | Agenten-Konvention | AKTUALISIEREN | AGENTS.md:1 | niedrig |
| `CHANGELOG.md` | Release-Notizen | docs/RELEASING.md:16 | AKTUALISIEREN | docs/RELEASING.md:16 | niedrig |
| `CONTRIBUTING.md` | Beitragsleitfaden | README.md:29 | AKTUALISIEREN | README.md:29 | niedrig |
| `Dockerfile.test` | ARM-Testcontainer | tests/README.md:165 | AKTUALISIEREN | tests/README.md:165 | mittel |
| `LICENSE.txt` | Lizenz | scripts/build_release.py:95-121 | BEHALTEN | scripts/build_release.py:95-121 | niedrig |
| `README.md` | Projekteinstieg | Repo-Einstiegsdatei | AKTUALISIEREN | README.md:1 | niedrig |
| `VERSION` | Release-Version | scripts/build_release.py:196 | BEHALTEN | scripts/build_release.py:196 | niedrig |
| `completeness.py` | Python-Modul | tests/test_things_completeness_matrix.py:6 | BEHALTEN | tests/test_things_completeness_matrix.py:6 | mittel |
| `config.json` | Generator-Defaults | config.py:23-25 | BEHALTEN | config.py:23-25 | hoch |
| `config.py` | Generator-Konfiguration | knxproject_to_openhab.py:15 | BEHALTEN | knxproject_to_openhab.py:15 | hoch |
| `docs/DEVELOPER_GUIDE.md` | Entwicklerdoku | README.md:29 | AKTUALISIEREN | README.md:29 | niedrig |
| `docs/PRODUCTION_GUIDE.md` | Betriebsdoku | README.md:28 | AKTUALISIEREN | README.md:28 | mittel |
| `docs/RELEASING.md` | Release-Anleitung | kein interner Link; Release-Anleitung | BEHALTEN | docs/RELEASING.md:1-24 | niedrig |
| `docs/REPO_CLEANUP_INVENTORY.md` | Historischer Audit | docs/REPO_CLEANUP_INVENTORY.md:3 | ZUSAMMENFÜHREN | docs/REPO_CLEANUP_INVENTORY.md:3 | mittel |
| `docs/SECURITY_UPLOAD.md` | Upload-Sicherheitsdoku | kein interner Link; Sicherheitsdoku | AKTUALISIEREN | docs/SECURITY_UPLOAD.md:1-5 | niedrig |
| `docs/USER_GUIDE.md` | Anwenderdoku | README.md:27 | AKTUALISIEREN | README.md:27 | niedrig |
| `docs/images/ui-home.png` | README-UI-Bild | README.md:119-125 | BEHALTEN | README.md:119-125 | niedrig |
| `docs/images/ui-settings.png` | README-UI-Bild | README.md:119-125 | BEHALTEN | README.md:119-125 | niedrig |
| `docs/screenshots/basic-auth-dashboard.png` | PR-UI-Beleg | kein interner Link; externer PR-Bezug ungeprüft | BEHALTEN | .github/PULL_REQUEST_TEMPLATE.md:25 | mittel |
| `docs/screenshots/gateway-ip-canonicalized.png` | PR-UI-Beleg | kein interner Link; externer PR-Bezug ungeprüft | BEHALTEN | .github/PULL_REQUEST_TEMPLATE.md:25 | mittel |
| `docs/screenshots/gateway-state-after-job-delete.png` | PR-UI-Beleg | kein interner Link; externer PR-Bezug ungeprüft | BEHALTEN | .github/PULL_REQUEST_TEMPLATE.md:25 | mittel |
| `docs/screenshots/gateway-state-after-rollback.png` | PR-UI-Beleg | kein interner Link; externer PR-Bezug ungeprüft | BEHALTEN | .github/PULL_REQUEST_TEMPLATE.md:25 | mittel |
| `docs/screenshots/gateway-undo-disabled-after-config-save.png` | PR-UI-Beleg | kein interner Link; externer PR-Bezug ungeprüft | BEHALTEN | .github/PULL_REQUEST_TEMPLATE.md:25 | mittel |
| `docs/screenshots/issue-38-generated-yaml.png` | PR-UI-Beleg | docs/screenshots/issue-38-yaml.md:4 | BEHALTEN | docs/screenshots/issue-38-yaml.md:4 | mittel |
| `docs/screenshots/issue-38-yaml-settings.png` | PR-UI-Beleg | docs/screenshots/issue-38-yaml.md:3 | BEHALTEN | docs/screenshots/issue-38-yaml.md:3 | mittel |
| `docs/screenshots/issue-38-yaml.md` | PR-UI-Beleg | kein interner Link; externer PR-Bezug ungeprüft | BEHALTEN | .github/PULL_REQUEST_TEMPLATE.md:25 | mittel |
| `docs/screenshots/issue-40-gateway-ip-settings.png` | PR-UI-Beleg | docs/screenshots/issue-40-gateway-ip.md:9 | BEHALTEN | docs/screenshots/issue-40-gateway-ip.md:9 | mittel |
| `docs/screenshots/issue-40-gateway-ip.md` | PR-UI-Beleg | kein interner Link; externer PR-Bezug ungeprüft | BEHALTEN | .github/PULL_REQUEST_TEMPLATE.md:25 | mittel |
| `docs/screenshots/issue-40-generated-knx-things.png` | PR-UI-Beleg | docs/screenshots/issue-40-gateway-ip.md:15 | BEHALTEN | docs/screenshots/issue-40-gateway-ip.md:15 | mittel |
| `docs/screenshots/issue-41-no-apt-package.png` | PR-UI-Beleg | kein interner Link; externer PR-Bezug ungeprüft | BEHALTEN | .github/PULL_REQUEST_TEMPLATE.md:25 | mittel |
| `docs/screenshots/issue-41-updates-available.png` | PR-UI-Beleg | kein interner Link; externer PR-Bezug ungeprüft | BEHALTEN | .github/PULL_REQUEST_TEMPLATE.md:25 | mittel |
| `docs/screenshots/issue-56-language-de.png` | PR-UI-Beleg | kein interner Link; externer PR-Bezug ungeprüft | BEHALTEN | .github/PULL_REQUEST_TEMPLATE.md:25 | mittel |
| `docs/screenshots/issue-56-language-en.png` | PR-UI-Beleg | kein interner Link; externer PR-Bezug ungeprüft | BEHALTEN | .github/PULL_REQUEST_TEMPLATE.md:25 | mittel |
| `docs/screenshots/issue-61-gateway-help-de.png` | PR-UI-Beleg | docs/screenshots/issue-61-gateway-reprocess-help.md:10 | BEHALTEN | docs/screenshots/issue-61-gateway-reprocess-help.md:10 | mittel |
| `docs/screenshots/issue-61-gateway-help-en.png` | PR-UI-Beleg | docs/screenshots/issue-61-gateway-reprocess-help.md:8 | BEHALTEN | docs/screenshots/issue-61-gateway-reprocess-help.md:8 | mittel |
| `docs/screenshots/issue-61-gateway-reprocess-help.md` | PR-UI-Beleg | kein interner Link; externer PR-Bezug ungeprüft | BEHALTEN | .github/PULL_REQUEST_TEMPLATE.md:25 | mittel |
| `docs/screenshots/knx-gateway-live-ip-applied.png` | PR-UI-Beleg | docs/screenshots/knx-gateway-live-ip.md:15 | BEHALTEN | docs/screenshots/knx-gateway-live-ip.md:15 | mittel |
| `docs/screenshots/knx-gateway-live-ip-settings.png` | PR-UI-Beleg | docs/screenshots/knx-gateway-live-ip.md:9 | BEHALTEN | docs/screenshots/knx-gateway-live-ip.md:9 | mittel |
| `docs/screenshots/knx-gateway-live-ip.md` | PR-UI-Beleg | docs/USER_GUIDE.md:142 | BEHALTEN | docs/USER_GUIDE.md:142 | mittel |
| `docs/screenshots/services-after-package-refresh.png` | PR-UI-Beleg | kein interner Link; externer PR-Bezug ungeprüft | BEHALTEN | .github/PULL_REQUEST_TEMPLATE.md:25 | mittel |
| `docs/superpowers/plans/2026-10-31-gateway-review-followup.md` | historischer Entwurf | nur interne Plan/Spec-Paare | ZUSAMMENFÜHREN | docs/superpowers/plans/2026-10-31-gateway-review-followup.md:1 | mittel |
| `docs/superpowers/plans/2026-10-31-live-gateway-main-yaml-integration.md` | historischer Entwurf | nur interne Plan/Spec-Paare | ZUSAMMENFÜHREN | docs/superpowers/plans/2026-10-31-live-gateway-main-yaml-integration.md:1 | mittel |
| `docs/superpowers/plans/2026-11-02-cookie-less-http-basic-auth.md` | historischer Entwurf | nur interne Plan/Spec-Paare | ZUSAMMENFÜHREN | docs/superpowers/plans/2026-11-02-cookie-less-http-basic-auth.md:1 | mittel |
| `docs/superpowers/plans/2026-11-02-login-csrf-origin-fallback.md` | historischer Entwurf | nur interne Plan/Spec-Paare | ZUSAMMENFÜHREN | docs/superpowers/plans/2026-11-02-login-csrf-origin-fallback.md:1 | mittel |
| `docs/superpowers/plans/2026-11-03-issue-25-installer-preflight.md` | historischer Entwurf | nur interne Plan/Spec-Paare | ZUSAMMENFÜHREN | docs/superpowers/plans/2026-11-03-issue-25-installer-preflight.md:1 | mittel |
| `docs/superpowers/plans/2026-11-03-pr-template-and-dev-branch.md` | historischer Entwurf | nur interne Plan/Spec-Paare | ZUSAMMENFÜHREN | docs/superpowers/plans/2026-11-03-pr-template-and-dev-branch.md:1 | mittel |
| `docs/superpowers/specs/2026-10-31-gateway-review-followup-design.md` | historischer Entwurf | nur interne Plan/Spec-Paare | ZUSAMMENFÜHREN | docs/superpowers/specs/2026-10-31-gateway-review-followup-design.md:1 | mittel |
| `docs/superpowers/specs/2026-10-31-live-gateway-main-yaml-integration-design.md` | historischer Entwurf | nur interne Plan/Spec-Paare | ZUSAMMENFÜHREN | docs/superpowers/specs/2026-10-31-live-gateway-main-yaml-integration-design.md:1 | mittel |
| `docs/superpowers/specs/2026-11-02-cookie-less-http-basic-auth-design.md` | historischer Entwurf | nur interne Plan/Spec-Paare | ZUSAMMENFÜHREN | docs/superpowers/specs/2026-11-02-cookie-less-http-basic-auth-design.md:1 | mittel |
| `docs/superpowers/specs/2026-11-02-login-csrf-origin-fallback-design.md` | historischer Entwurf | nur interne Plan/Spec-Paare | ZUSAMMENFÜHREN | docs/superpowers/specs/2026-11-02-login-csrf-origin-fallback-design.md:1 | mittel |
| `docs/superpowers/specs/2026-11-03-issue-25-installer-preflight-design.md` | historischer Entwurf | nur interne Plan/Spec-Paare | ZUSAMMENFÜHREN | docs/superpowers/specs/2026-11-03-issue-25-installer-preflight-design.md:1 | mittel |
| `docs/superpowers/specs/2026-11-03-pr-template-and-dev-branch-design.md` | historischer Entwurf | nur interne Plan/Spec-Paare | ZUSAMMENFÜHREN | docs/superpowers/specs/2026-11-03-pr-template-and-dev-branch-design.md:1 | mittel |
| `ets_helpers.py` | Python-Modul | ets_to_openhab.py:10 | BEHALTEN | ets_to_openhab.py:10 | mittel |
| `ets_to_openhab.py` | Python-Modul | knxproject_to_openhab.py:14 | BEHALTEN | knxproject_to_openhab.py:14 | mittel |
| `fix_permissions.sh` | Reparaturrechte | docs/PRODUCTION_GUIDE.md:457 | BEHALTEN | docs/PRODUCTION_GUIDE.md:457 | hoch |
| `install.sh` | Release-Installer | docs/PRODUCTION_GUIDE.md:51 | BEHALTEN | docs/PRODUCTION_GUIDE.md:51 | hoch |
| `installer/README.md` | Installer-Doku | README.md:85 | AKTUALISIEREN | README.md:85 | niedrig |
| `installer/__init__.py` | Installer-Helfer | tests/test_managed_output_provisioner.py:7 | BEHALTEN | tests/test_managed_output_provisioner.py:7 | mittel |
| `installer/backup_cleanup.sh` | Installer-Helfer | installer/launch_backup_cleanup.sh:6-15 | BEHALTEN | installer/launch_backup_cleanup.sh:6-15 | hoch |
| `installer/configure_auth.py` | Installer-Helfer | tests/test_configure_auth.py:9 | BEHALTEN | tests/test_configure_auth.py:9 | mittel |
| `installer/configure_bind.py` | Installer-Helfer | tests/test_configure_bind.py:3 | BEHALTEN | tests/test_configure_bind.py:3 | mittel |
| `installer/knxohui-backup-cleanup.service` | Installer-Helfer | installer/setup.sh:302-303 | BEHALTEN | installer/setup.sh:302-303 | hoch |
| `installer/knxohui-backup-cleanup.timer` | Installer-Helfer | installer/setup.sh:304-305 | BEHALTEN | installer/setup.sh:304-305 | hoch |
| `installer/knxohui.service` | Installer-Helfer | installer/setup.sh:300-301 | BEHALTEN | installer/setup.sh:300-301 | hoch |
| `installer/knxohui.sudoers` | Installer-Helfer | installer/migrate_sudoers.sh:5 | BEHALTEN | installer/migrate_sudoers.sh:5 | hoch |
| `installer/launch_backup_cleanup.sh` | Installer-Helfer | installer/knxohui-backup-cleanup.service:10 | BEHALTEN | installer/knxohui-backup-cleanup.service:10 | hoch |
| `installer/launch_web.sh` | Installer-Helfer | installer/knxohui.service:11 | BEHALTEN | installer/knxohui.service:11 | hoch |
| `installer/migrate_runtime_data.py` | Installer-Helfer | installer/setup.sh:236 | BEHALTEN | installer/setup.sh:236 | mittel |
| `installer/migrate_sudoers.sh` | Installer-Helfer | fix_permissions.sh:68 | BEHALTEN | fix_permissions.sh:68 | hoch |
| `installer/provision_managed_files.py` | Installer-Helfer | fix_permissions.sh:53 | BEHALTEN | fix_permissions.sh:53 | mittel |
| `installer/provision_managed_outputs.py` | Installer-Helfer | installer/setup.sh:232-233 | BEHALTEN | installer/setup.sh:232-233 | mittel |
| `installer/service_update.sh` | Installer-Helfer | fix_permissions.sh:57 | BEHALTEN | fix_permissions.sh:57 | hoch |
| `installer/set_ui_password.py` | Installer-Helfer | tests/test_set_ui_password.py:5 | BEHALTEN | tests/test_set_ui_password.py:5 | mittel |
| `installer/setup.sh` | Installer-Helfer | install.sh:648-655 | BEHALTEN | install.sh:648-655 | hoch |
| `installer/web_ui_endpoint.py` | Installer-Helfer | install.sh:667 | BEHALTEN | install.sh:667 | mittel |
| `items.template` | Legacy-Items-Wrapper | ets_to_openhab.py:991-993 | BEHALTEN | ets_to_openhab.py:991-993 | hoch |
| `knxoh_paths.py` | Python-Modul | config.py:9 | BEHALTEN | config.py:9 | mittel |
| `knxproject_to_openhab.py` | Python-Modul | scripts/generate_golden_files.py:29 | BEHALTEN | scripts/generate_golden_files.py:29 | mittel |
| `openhab/icons/classic/heating_mode-1.svg` | openHAB-Icon | generiertes Icon heating_mode | BEHALTEN | ets_to_openhab.py:607; config.json:107 | mittel |
| `openhab/icons/classic/heating_mode-2.svg` | openHAB-Icon | generiertes Icon heating_mode | BEHALTEN | ets_to_openhab.py:607; config.json:107 | mittel |
| `openhab/icons/classic/heating_mode-3.svg` | openHAB-Icon | generiertes Icon heating_mode | BEHALTEN | ets_to_openhab.py:607; config.json:107 | mittel |
| `openhab/icons/classic/heating_mode-4.svg` | openHAB-Icon | generiertes Icon heating_mode | BEHALTEN | ets_to_openhab.py:607; config.json:107 | mittel |
| `openhab/icons/classic/heating_mode.svg` | openHAB-Icon | generiertes Icon heating_mode | BEHALTEN | ets_to_openhab.py:607; config.json:107 | mittel |
| `openhab_yaml.py` | Python-Modul | ets_to_openhab.py:11 | BEHALTEN | ets_to_openhab.py:11 | mittel |
| `pyproject.toml` | Formatter/Typkonfig | .github/workflows/ci.yml:80-88 | BEHALTEN | .github/workflows/ci.yml:80-88 | niedrig |
| `pytest.ini` | pytest-Konfig | tests/README.md:54-57 | AKTUALISIEREN | tests/README.md:54-57 | mittel |
| `requirements-dev.txt` | Test-/Entwicklungspakete | .github/workflows/ci.yml:45-46 | AKTUALISIEREN | .github/workflows/ci.yml:45-46 | mittel |
| `requirements.txt` | Produktionspakete | installer/setup.sh:221-296 | AKTUALISIEREN | installer/setup.sh:221-296 | mittel |
| `scripts/__init__.py` | Entwickler-/Release-Helfer | Paketmarker; kein direkter Aufruf | BEHALTEN | scripts/__init__.py:1 | niedrig |
| `scripts/build_release.py` | Entwickler-/Release-Helfer | .github/workflows/release.yml:32 | BEHALTEN | .github/workflows/release.yml:32 | niedrig |
| `scripts/dev-run.ps1` | Entwickler-/Release-Helfer | docs/DEVELOPER_GUIDE.md:32 | BEHALTEN | docs/DEVELOPER_GUIDE.md:32 | niedrig |
| `scripts/dev-run.sh` | Entwickler-/Release-Helfer | docs/DEVELOPER_GUIDE.md:43 | BEHALTEN | docs/DEVELOPER_GUIDE.md:43 | niedrig |
| `scripts/dev-setup.ps1` | Entwickler-/Release-Helfer | docs/DEVELOPER_GUIDE.md:29 | BEHALTEN | docs/DEVELOPER_GUIDE.md:29 | niedrig |
| `scripts/dev-setup.sh` | Entwickler-/Release-Helfer | docs/DEVELOPER_GUIDE.md:43 | BEHALTEN | docs/DEVELOPER_GUIDE.md:43 | niedrig |
| `scripts/generate_golden_files.py` | Entwickler-/Release-Helfer | docs/DEVELOPER_GUIDE.md:319 | BEHALTEN | docs/DEVELOPER_GUIDE.md:319 | niedrig |
| `scripts/regenerate_golden.py` | Entwickler-/Release-Helfer | .github/copilot-instructions.md:54 | BEHALTEN | .github/copilot-instructions.md:54 | niedrig |
| `scripts/verify-setup.ps1` | Entwickler-/Release-Helfer | docs/DEVELOPER_GUIDE.md:150 | BEHALTEN | docs/DEVELOPER_GUIDE.md:150 | niedrig |
| `scripts/verify-setup.sh` | Entwickler-/Release-Helfer | scripts/dev-setup.sh:93 | BEHALTEN | scripts/dev-setup.sh:93 | niedrig |
| `sitemap.template` | Legacy-Sitemap-Wrapper | ets_to_openhab.py:1005-1007 | BEHALTEN | ets_to_openhab.py:1005-1007 | hoch |
| `tests/Charne.knxproj.json` | ETS-JSON-Fixture | tests/integration/test_output_validation.py:28 | BEHALTEN | tests/integration/test_output_validation.py:28 | hoch |
| `tests/README.md` | Testanleitung | CONTRIBUTING.md:99 | AKTUALISIEREN | CONTRIBUTING.md:99 | niedrig |
| `tests/__init__.py` | Kern-/Integrationstest | pytest.ini:5-8; .github/workflows/ci.yml:50 | BEHALTEN | pytest.ini:5-8; .github/workflows/ci.yml:50 | niedrig |
| `tests/conftest.py` | Kern-/Integrationstest | pytest.ini:5-8; .github/workflows/ci.yml:50 | BEHALTEN | pytest.ini:5-8; .github/workflows/ci.yml:50 | niedrig |
| `tests/fixtures/Charne.knxproj` | Echtes ETS-Archiv | tests/ui/test_upload_flow.py:9 | BEHALTEN | tests/ui/test_upload_flow.py:9 | hoch |
| `tests/fixtures/expected_output/Charne/README.md` | Golden-Referenz | tests/integration/test_output_validation.py:28-60 | BEHALTEN | tests/integration/test_output_validation.py:28-60 | mittel |
| `tests/fixtures/expected_output/Charne/knx.items` | Golden-Referenz | tests/integration/test_output_validation.py:28-60 | BEHALTEN | tests/integration/test_output_validation.py:28-60 | mittel |
| `tests/fixtures/expected_output/Charne/knx.sitemap` | Golden-Referenz | tests/integration/test_output_validation.py:28-60 | BEHALTEN | tests/integration/test_output_validation.py:28-60 | mittel |
| `tests/fixtures/expected_output/Charne/knx.things` | Golden-Referenz | tests/integration/test_output_validation.py:28-60 | BEHALTEN | tests/integration/test_output_validation.py:28-60 | mittel |
| `tests/fixtures/expected_output/Mini/README.md` | Golden-Referenz | tests/integration/test_output_validation.py:28-60 | BEHALTEN | tests/integration/test_output_validation.py:28-60 | mittel |
| `tests/fixtures/expected_output/Mini/knx.items` | Golden-Referenz | tests/integration/test_output_validation.py:28-60 | BEHALTEN | tests/integration/test_output_validation.py:28-60 | mittel |
| `tests/fixtures/expected_output/Mini/knx.sitemap` | Golden-Referenz | tests/integration/test_output_validation.py:28-60 | BEHALTEN | tests/integration/test_output_validation.py:28-60 | mittel |
| `tests/fixtures/expected_output/Mini/knx.things` | Golden-Referenz | tests/integration/test_output_validation.py:28-60 | BEHALTEN | tests/integration/test_output_validation.py:28-60 | mittel |
| `tests/fixtures/expected_output/UploadJson/README.md` | Golden-Referenz | tests/integration/test_output_validation.py:28-60 | BEHALTEN | tests/integration/test_output_validation.py:28-60 | mittel |
| `tests/fixtures/expected_output/UploadJson/knx.items` | Golden-Referenz | tests/integration/test_output_validation.py:28-60 | BEHALTEN | tests/integration/test_output_validation.py:28-60 | mittel |
| `tests/fixtures/expected_output/UploadJson/knx.sitemap` | Golden-Referenz | tests/integration/test_output_validation.py:28-60 | BEHALTEN | tests/integration/test_output_validation.py:28-60 | mittel |
| `tests/fixtures/expected_output/UploadJson/knx.things` | Golden-Referenz | tests/integration/test_output_validation.py:28-60 | BEHALTEN | tests/integration/test_output_validation.py:28-60 | mittel |
| `tests/fixtures/expected_output/common/README.md` | Golden-Referenz | tests/integration/test_output_validation.py:28-60 | BEHALTEN | tests/integration/test_output_validation.py:28-60 | mittel |
| `tests/fixtures/expected_output/common/influxdb.persist` | Golden-Referenz | tests/integration/test_output_validation.py:28-60 | BEHALTEN | tests/integration/test_output_validation.py:28-60 | mittel |
| `tests/fixtures/mini_project.json` | Mini-Fixture | tests/integration/test_output_validation.py:28 | BEHALTEN | tests/integration/test_output_validation.py:28 | mittel |
| `tests/fixtures/synthetic_openhab_5_2.yaml` | YAML-Testfixture | tests/test_openhab_yaml.py:1 | BEHALTEN | tests/test_openhab_yaml.py:1 | mittel |
| `tests/integration/test_business_logic.py` | Kern-/Integrationstest | pytest.ini:5-8; .github/workflows/ci.yml:50 | BEHALTEN | pytest.ini:5-8; .github/workflows/ci.yml:50 | niedrig |
| `tests/integration/test_file_import.py` | Kern-/Integrationstest | pytest.ini:5-8; .github/workflows/ci.yml:50 | BEHALTEN | pytest.ini:5-8; .github/workflows/ci.yml:50 | niedrig |
| `tests/integration/test_installer.py` | Kern-/Integrationstest | pytest.ini:5-8; .github/workflows/ci.yml:50 | BEHALTEN | pytest.ini:5-8; .github/workflows/ci.yml:50 | niedrig |
| `tests/integration/test_output_validation.py` | Kern-/Integrationstest | pytest.ini:5-8; .github/workflows/ci.yml:50 | BEHALTEN | pytest.ini:5-8; .github/workflows/ci.yml:50 | niedrig |
| `tests/test_address_selection.py` | Kern-/Integrationstest | pytest.ini:5-8; .github/workflows/ci.yml:50 | BEHALTEN | pytest.ini:5-8; .github/workflows/ci.yml:50 | niedrig |
| `tests/test_api_schema.py` | Kern-/Integrationstest | pytest.ini:5-8; .github/workflows/ci.yml:50 | BEHALTEN | pytest.ini:5-8; .github/workflows/ci.yml:50 | niedrig |
| `tests/test_auto_place_unknowns.py` | Kern-/Integrationstest | pytest.ini:5-8; .github/workflows/ci.yml:50 | BEHALTEN | pytest.ini:5-8; .github/workflows/ci.yml:50 | niedrig |
| `tests/test_configure_auth.py` | Kern-/Integrationstest | pytest.ini:5-8; .github/workflows/ci.yml:50 | BEHALTEN | pytest.ini:5-8; .github/workflows/ci.yml:50 | niedrig |
| `tests/test_configure_bind.py` | Kern-/Integrationstest | pytest.ini:5-8; .github/workflows/ci.yml:50 | BEHALTEN | pytest.ini:5-8; .github/workflows/ci.yml:50 | niedrig |
| `tests/test_core_functionality.py` | Kern-/Integrationstest | pytest.ini:5-8; .github/workflows/ci.yml:50 | BEHALTEN | pytest.ini:5-8; .github/workflows/ci.yml:50 | niedrig |
| `tests/test_deploy_policy.py` | Kern-/Integrationstest | pytest.ini:5-8; .github/workflows/ci.yml:50 | BEHALTEN | pytest.ini:5-8; .github/workflows/ci.yml:50 | niedrig |
| `tests/test_ets_helpers.py` | Kern-/Integrationstest | pytest.ini:5-8; .github/workflows/ci.yml:50 | BEHALTEN | pytest.ini:5-8; .github/workflows/ci.yml:50 | niedrig |
| `tests/test_external_deps_mocking.py` | Kern-/Integrationstest | pytest.ini:5-8; .github/workflows/ci.yml:50 | BEHALTEN | pytest.ini:5-8; .github/workflows/ci.yml:50 | niedrig |
| `tests/test_full_generation.py` | Kern-/Integrationstest | pytest.ini:5-8; .github/workflows/ci.yml:50 | BEHALTEN | pytest.ini:5-8; .github/workflows/ci.yml:50 | niedrig |
| `tests/test_gateway_ip.py` | Kern-/Integrationstest | pytest.ini:5-8; .github/workflows/ci.yml:50 | BEHALTEN | pytest.ini:5-8; .github/workflows/ci.yml:50 | niedrig |
| `tests/test_gateway_live_update.py` | Kern-/Integrationstest | pytest.ini:5-8; .github/workflows/ci.yml:50 | BEHALTEN | pytest.ini:5-8; .github/workflows/ci.yml:50 | niedrig |
| `tests/test_installer_guardrails.py` | Kern-/Integrationstest | pytest.ini:5-8; .github/workflows/ci.yml:50 | BEHALTEN | pytest.ini:5-8; .github/workflows/ci.yml:50 | niedrig |
| `tests/test_installer_modes.py` | Kern-/Integrationstest | pytest.ini:5-8; .github/workflows/ci.yml:50 | BEHALTEN | pytest.ini:5-8; .github/workflows/ci.yml:50 | niedrig |
| `tests/test_installer_preflight.py` | Kern-/Integrationstest | pytest.ini:5-8; .github/workflows/ci.yml:50 | BEHALTEN | pytest.ini:5-8; .github/workflows/ci.yml:50 | niedrig |
| `tests/test_job_deploy_permissions.py` | Kern-/Integrationstest | pytest.ini:5-8; .github/workflows/ci.yml:50 | BEHALTEN | pytest.ini:5-8; .github/workflows/ci.yml:50 | niedrig |
| `tests/test_knxoh_paths.py` | Kern-/Integrationstest | pytest.ini:5-8; .github/workflows/ci.yml:50 | BEHALTEN | pytest.ini:5-8; .github/workflows/ci.yml:50 | niedrig |
| `tests/test_managed_output_provisioner.py` | Kern-/Integrationstest | pytest.ini:5-8; .github/workflows/ci.yml:50 | BEHALTEN | pytest.ini:5-8; .github/workflows/ci.yml:50 | niedrig |
| `tests/test_mini_fixture_regressions.py` | Kern-/Integrationstest | pytest.ini:5-8; .github/workflows/ci.yml:50 | BEHALTEN | pytest.ini:5-8; .github/workflows/ci.yml:50 | niedrig |
| `tests/test_openhab_yaml.py` | Kern-/Integrationstest | pytest.ini:5-8; .github/workflows/ci.yml:50 | BEHALTEN | pytest.ini:5-8; .github/workflows/ci.yml:50 | niedrig |
| `tests/test_output_config.py` | Kern-/Integrationstest | pytest.ini:5-8; .github/workflows/ci.yml:50 | BEHALTEN | pytest.ini:5-8; .github/workflows/ci.yml:50 | niedrig |
| `tests/test_output_regressions.py` | Kern-/Integrationstest | pytest.ini:5-8; .github/workflows/ci.yml:50 | BEHALTEN | pytest.ini:5-8; .github/workflows/ci.yml:50 | niedrig |
| `tests/test_output_syntax_validation.py` | Kern-/Integrationstest | pytest.ini:5-8; .github/workflows/ci.yml:50 | BEHALTEN | pytest.ini:5-8; .github/workflows/ci.yml:50 | niedrig |
| `tests/test_password_auth.py` | Kern-/Integrationstest | pytest.ini:5-8; .github/workflows/ci.yml:50 | BEHALTEN | pytest.ini:5-8; .github/workflows/ci.yml:50 | niedrig |
| `tests/test_privilege_policy.py` | Kern-/Integrationstest | pytest.ini:5-8; .github/workflows/ci.yml:50 | BEHALTEN | pytest.ini:5-8; .github/workflows/ci.yml:50 | niedrig |
| `tests/test_project_preview.py` | Kern-/Integrationstest | pytest.ini:5-8; .github/workflows/ci.yml:50 | BEHALTEN | pytest.ini:5-8; .github/workflows/ci.yml:50 | niedrig |
| `tests/test_release_artifacts.py` | Kern-/Integrationstest | pytest.ini:5-8; .github/workflows/ci.yml:50 | BEHALTEN | pytest.ini:5-8; .github/workflows/ci.yml:50 | niedrig |
| `tests/test_release_selection.py` | Kern-/Integrationstest | pytest.ini:5-8; .github/workflows/ci.yml:50 | BEHALTEN | pytest.ini:5-8; .github/workflows/ci.yml:50 | niedrig |
| `tests/test_repository_hygiene.py` | Kern-/Integrationstest | pytest.ini:5-8; .github/workflows/ci.yml:50 | BEHALTEN | pytest.ini:5-8; .github/workflows/ci.yml:50 | niedrig |
| `tests/test_runtime_data_migration.py` | Kern-/Integrationstest | pytest.ini:5-8; .github/workflows/ci.yml:50 | BEHALTEN | pytest.ini:5-8; .github/workflows/ci.yml:50 | niedrig |
| `tests/test_service_manager.py` | Kern-/Integrationstest | pytest.ini:5-8; .github/workflows/ci.yml:50 | BEHALTEN | pytest.ini:5-8; .github/workflows/ci.yml:50 | niedrig |
| `tests/test_service_updates.py` | Kern-/Integrationstest | pytest.ini:5-8; .github/workflows/ci.yml:50 | BEHALTEN | pytest.ini:5-8; .github/workflows/ci.yml:50 | niedrig |
| `tests/test_session_store.py` | Kern-/Integrationstest | pytest.ini:5-8; .github/workflows/ci.yml:50 | BEHALTEN | pytest.ini:5-8; .github/workflows/ci.yml:50 | niedrig |
| `tests/test_set_ui_password.py` | Kern-/Integrationstest | pytest.ini:5-8; .github/workflows/ci.yml:50 | BEHALTEN | pytest.ini:5-8; .github/workflows/ci.yml:50 | niedrig |
| `tests/test_things_completeness.py` | Kern-/Integrationstest | pytest.ini:5-8; .github/workflows/ci.yml:50 | BEHALTEN | pytest.ini:5-8; .github/workflows/ci.yml:50 | niedrig |
| `tests/test_things_completeness_matrix.py` | Kern-/Integrationstest | pytest.ini:5-8; .github/workflows/ci.yml:50 | BEHALTEN | pytest.ini:5-8; .github/workflows/ci.yml:50 | niedrig |
| `tests/test_things_format_jobs.py` | Kern-/Integrationstest | pytest.ini:5-8; .github/workflows/ci.yml:50 | BEHALTEN | pytest.ini:5-8; .github/workflows/ci.yml:50 | niedrig |
| `tests/test_uninstall_modes.py` | Kern-/Integrationstest | pytest.ini:5-8; .github/workflows/ci.yml:50 | BEHALTEN | pytest.ini:5-8; .github/workflows/ci.yml:50 | niedrig |
| `tests/test_updater.py` | Kern-/Integrationstest | pytest.ini:5-8; .github/workflows/ci.yml:50 | BEHALTEN | pytest.ini:5-8; .github/workflows/ci.yml:50 | niedrig |
| `tests/test_upload_security.py` | Kern-/Integrationstest | pytest.ini:5-8; .github/workflows/ci.yml:50 | BEHALTEN | pytest.ini:5-8; .github/workflows/ci.yml:50 | niedrig |
| `tests/test_web_ui_endpoint.py` | Kern-/Integrationstest | pytest.ini:5-8; .github/workflows/ci.yml:50 | BEHALTEN | pytest.ini:5-8; .github/workflows/ci.yml:50 | niedrig |
| `tests/test_web_ui_job_endpoints.py` | Kern-/Integrationstest | pytest.ini:5-8; .github/workflows/ci.yml:50 | BEHALTEN | pytest.ini:5-8; .github/workflows/ci.yml:50 | niedrig |
| `tests/test_web_ui_job_stats.py` | Kern-/Integrationstest | pytest.ini:5-8; .github/workflows/ci.yml:50 | BEHALTEN | pytest.ini:5-8; .github/workflows/ci.yml:50 | niedrig |
| `tests/ui/README.md` | UI-Testanleitung | kein interner Link; UI-Testanleitung | AKTUALISIEREN | tests/ui/README.md:1-4 | niedrig |
| `tests/ui/__init__.py` | UI-Test/Fixture | pytest.ini:5-8; .github/workflows/ci.yml:137 | BEHALTEN | pytest.ini:5-8; .github/workflows/ci.yml:137 | niedrig |
| `tests/ui/conftest.py` | UI-Test/Fixture | pytest.ini:5-8; .github/workflows/ci.yml:137 | BEHALTEN | pytest.ini:5-8; .github/workflows/ci.yml:137 | niedrig |
| `tests/ui/setup_test_env.py` | UI-Test/Fixture | pytest.ini:5-8; .github/workflows/ci.yml:137 | BEHALTEN | pytest.ini:5-8; .github/workflows/ci.yml:137 | niedrig |
| `tests/ui/test_auth_screenshots.py` | UI-Test/Fixture | pytest.ini:5-8; .github/workflows/ci.yml:137 | BEHALTEN | pytest.ini:5-8; .github/workflows/ci.yml:137 | niedrig |
| `tests/ui/test_auth_session.py` | UI-Test/Fixture | pytest.ini:5-8; .github/workflows/ci.yml:137 | BEHALTEN | pytest.ini:5-8; .github/workflows/ci.yml:137 | niedrig |
| `tests/ui/test_file_preview.py` | UI-Test/Fixture | pytest.ini:5-8; .github/workflows/ci.yml:137 | BEHALTEN | pytest.ini:5-8; .github/workflows/ci.yml:137 | niedrig |
| `tests/ui/test_gateway_live_update.py` | UI-Test/Fixture | pytest.ini:5-8; .github/workflows/ci.yml:137 | BEHALTEN | pytest.ini:5-8; .github/workflows/ci.yml:137 | niedrig |
| `tests/ui/test_job_actions.py` | UI-Test/Fixture | pytest.ini:5-8; .github/workflows/ci.yml:137 | BEHALTEN | pytest.ini:5-8; .github/workflows/ci.yml:137 | niedrig |
| `tests/ui/test_job_lifecycle_e2e.py` | UI-Test/Fixture | pytest.ini:5-8; .github/workflows/ci.yml:137 | BEHALTEN | pytest.ini:5-8; .github/workflows/ci.yml:137 | niedrig |
| `tests/ui/test_language.py` | UI-Test/Fixture | pytest.ini:5-8; .github/workflows/ci.yml:137 | BEHALTEN | pytest.ini:5-8; .github/workflows/ci.yml:137 | niedrig |
| `tests/ui/test_output_format_config.py` | UI-Test/Fixture | pytest.ini:5-8; .github/workflows/ci.yml:137 | BEHALTEN | pytest.ini:5-8; .github/workflows/ci.yml:137 | niedrig |
| `tests/ui/test_preview_dialog.py` | UI-Test/Fixture | pytest.ini:5-8; .github/workflows/ci.yml:137 | BEHALTEN | pytest.ini:5-8; .github/workflows/ci.yml:137 | niedrig |
| `tests/ui/test_project_preview.py` | UI-Test/Fixture | pytest.ini:5-8; .github/workflows/ci.yml:137 | BEHALTEN | pytest.ini:5-8; .github/workflows/ci.yml:137 | niedrig |
| `tests/ui/test_service_update_polling.py` | UI-Test/Fixture | pytest.ini:5-8; .github/workflows/ci.yml:137 | BEHALTEN | pytest.ini:5-8; .github/workflows/ci.yml:137 | niedrig |
| `tests/ui/test_services_cloud.py` | UI-Test/Fixture | pytest.ini:5-8; .github/workflows/ci.yml:137 | BEHALTEN | pytest.ini:5-8; .github/workflows/ci.yml:137 | niedrig |
| `tests/ui/test_settings_advanced.py` | UI-Test/Fixture | pytest.ini:5-8; .github/workflows/ci.yml:137 | BEHALTEN | pytest.ini:5-8; .github/workflows/ci.yml:137 | niedrig |
| `tests/ui/test_settings_config.py` | UI-Test/Fixture | pytest.ini:5-8; .github/workflows/ci.yml:137 | BEHALTEN | pytest.ini:5-8; .github/workflows/ci.yml:137 | niedrig |
| `tests/ui/test_smoke.py` | UI-Test/Fixture | pytest.ini:5-8; .github/workflows/ci.yml:137 | BEHALTEN | pytest.ini:5-8; .github/workflows/ci.yml:137 | niedrig |
| `tests/ui/test_sse_streaming.py` | UI-Test/Fixture | pytest.ini:5-8; .github/workflows/ci.yml:137 | BEHALTEN | pytest.ini:5-8; .github/workflows/ci.yml:137 | niedrig |
| `tests/ui/test_ui_smoke.py` | UI-Test/Fixture | pytest.ini:5-8; .github/workflows/ci.yml:137 | BEHALTEN | pytest.ini:5-8; .github/workflows/ci.yml:137 | niedrig |
| `tests/ui/test_update_system.py` | UI-Test/Fixture | pytest.ini:5-8; .github/workflows/ci.yml:137 | BEHALTEN | pytest.ini:5-8; .github/workflows/ci.yml:137 | niedrig |
| `tests/ui/test_upload_flow.py` | UI-Test/Fixture | pytest.ini:5-8; .github/workflows/ci.yml:137 | BEHALTEN | pytest.ini:5-8; .github/workflows/ci.yml:137 | niedrig |
| `tests/ui/test_upload_job_happy_path.py` | UI-Test/Fixture | pytest.ini:5-8; .github/workflows/ci.yml:137 | BEHALTEN | pytest.ini:5-8; .github/workflows/ci.yml:137 | niedrig |
| `tests/ui/test_upload_security.py` | UI-Test/Fixture | pytest.ini:5-8; .github/workflows/ci.yml:137 | BEHALTEN | pytest.ini:5-8; .github/workflows/ci.yml:137 | niedrig |
| `tests/ui/test_web_interface.py` | UI-Test/Fixture | pytest.ini:5-8; .github/workflows/ci.yml:137 | BEHALTEN | pytest.ini:5-8; .github/workflows/ci.yml:137 | niedrig |
| `tests/upload.knxprojarchive.json` | Archiv-JSON-Fixture | tests/integration/test_output_validation.py:28 | BEHALTEN | tests/integration/test_output_validation.py:28 | mittel |
| `things.template` | Legacy-Things-Wrapper | ets_to_openhab.py:967-979 | BEHALTEN | ets_to_openhab.py:967-979 | hoch |
| `uninstall.sh` | Deinstaller | docs/PRODUCTION_GUIDE.md:137 | BEHALTEN | docs/PRODUCTION_GUIDE.md:137 | hoch |
| `update.sh` | Web-Update-Skript | web_ui/backend/updater.py:306 | BEHALTEN | web_ui/backend/updater.py:306 | hoch |
| `utils.py` | Python-Modul | ets_to_openhab.py:23 | BEHALTEN | ets_to_openhab.py:23 | mittel |
| `web_ui/README.md` | Web-UI-Doku | kein interner Link; Web-UI-Anleitung | AKTUALISIEREN | web_ui/README.md:1-5 | niedrig |
| `web_ui/__init__.py` | Python-Modul | Paketgrenze für web_ui.backend | BEHALTEN | web_ui/backend/__main__.py:6 | mittel |
| `web_ui/api_schema.json` | API-Schema | tests/test_api_schema.py:6 | BEHALTEN | tests/test_api_schema.py:6 | mittel |
| `web_ui/backend/__init__.py` | Python-Modul | Paketgrenze für relative Imports | BEHALTEN | web_ui/backend/app.py:53-60 | mittel |
| `web_ui/backend/__main__.py` | Python-Modul | python -m web_ui.backend (Modul-Einstieg) | BEHALTEN | web_ui/backend/__main__.py:8 | mittel |
| `web_ui/backend/app.py` | Python-Modul | tests/test_upload_security.py:637 | BEHALTEN | tests/test_upload_security.py:637 | mittel |
| `web_ui/backend/auth.py` | Python-Modul | installer/configure_auth.py:20 | BEHALTEN | installer/configure_auth.py:20 | mittel |
| `web_ui/backend/config.json` | Web-UI-Defaults | web_ui/backend/storage.py:33-35 | BEHALTEN | web_ui/backend/storage.py:33-35 | hoch |
| `web_ui/backend/config_schema.json` | Eingabeschema | web_ui/backend/app.py:1234-1237 | BEHALTEN | web_ui/backend/app.py:1234-1237 | mittel |
| `web_ui/backend/deploy_policy.py` | Python-Modul | installer/provision_managed_files.py:18 | BEHALTEN | installer/provision_managed_files.py:18 | mittel |
| `web_ui/backend/gateway_config.py` | Python-Modul | tests/test_gateway_live_update.py:19 | BEHALTEN | tests/test_gateway_live_update.py:19 | mittel |
| `web_ui/backend/gateway_undo.py` | Python-Modul | web_ui/backend/jobs.py:23 | BEHALTEN | web_ui/backend/jobs.py:23 | mittel |
| `web_ui/backend/gunicorn_conf.py` | Python-Modul | installer/launch_web.sh:18-19 | BEHALTEN | installer/launch_web.sh:18-19 | mittel |
| `web_ui/backend/jobs.py` | Python-Modul | tests/test_gateway_live_update.py:25 | BEHALTEN | tests/test_gateway_live_update.py:25 | mittel |
| `web_ui/backend/project_preview.py` | Python-Modul | tests/test_project_preview.py:9 | BEHALTEN | tests/test_project_preview.py:9 | mittel |
| `web_ui/backend/service_manager.py` | Python-Modul | web_ui/backend/app.py:55 | BEHALTEN | web_ui/backend/app.py:55 | mittel |
| `web_ui/backend/service_updates.py` | Python-Modul | web_ui/backend/app.py:56 | BEHALTEN | web_ui/backend/app.py:56 | mittel |
| `web_ui/backend/session_store.py` | Python-Modul | tests/test_session_store.py:5 | BEHALTEN | tests/test_session_store.py:5 | mittel |
| `web_ui/backend/storage.py` | Python-Modul | tests/test_knxoh_paths.py:3 | BEHALTEN | tests/test_knxoh_paths.py:3 | mittel |
| `web_ui/backend/things_format.py` | Python-Modul | tests/test_gateway_live_update.py:26 | BEHALTEN | tests/test_gateway_live_update.py:26 | mittel |
| `web_ui/backend/updater.py` | Python-Modul | tests/test_updater.py:6 | BEHALTEN | tests/test_updater.py:6 | mittel |
| `web_ui/backend/upload_security.py` | Python-Modul | tests/test_upload_security.py:33 | BEHALTEN | tests/test_upload_security.py:33 | mittel |
| `web_ui/static/app.js` | Web-UI-Logik | web_ui/templates/index.html:415 | BEHALTEN | web_ui/templates/index.html:415 | hoch |
| `web_ui/static/favicon.png` | UI-Favicon | web_ui/templates/index.html:10 | BEHALTEN | web_ui/templates/index.html:10 | niedrig |
| `web_ui/static/i18n.js` | UI-Übersetzungen | web_ui/templates/index.html:414 | BEHALTEN | web_ui/templates/index.html:414 | mittel |
| `web_ui/static/style.css` | UI-Stil | web_ui/templates/index.html:9 | BEHALTEN | web_ui/templates/index.html:9 | niedrig |
| `web_ui/templates/index.html` | UI-Haupttemplate | web_ui/backend/app.py:480-490 | BEHALTEN | web_ui/backend/app.py:480-490 | hoch |
| `web_ui/templates/login.html` | Login-Template | web_ui/backend/app.py:245 | BEHALTEN | web_ui/backend/app.py:245 | hoch |
