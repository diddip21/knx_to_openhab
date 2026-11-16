# KI-Workflow mit `dev`: Kurz-Checkliste zum Merge

**Stand: 16.11.2026.** Status ist kein Live-Dashboard. Immer die **aktuelle Commit-SHA**
und die neuesten GitHub-Actions-Runs in den verlinkten PRs vergleichen.

## Branch-Konzept

- **`main`** ist GitHubs **Default-Branch**: freigegebener/releasbarer Stand,
  trusted Issue-/Workflow-Controller, `workflow_run`-Empfänger.
- **`dev`** ist der Zielbranch für KI-Feature-PRs, Reviews und Integration.
- **`ai/issue-*`** sind temporäre Arbeitsbranches für freigegebene Issues.
- **Release:** nach geprüfter Integration ein **eigener PR von `dev` nach `main`**.
  **Weder Agent noch Publisher dürfen automatisch mergen.**

## Reihenfolge bei der Umstellung – wichtig

1. **Zuerst #109** mit grüner CI und Security-Review **manuell nach `main` mergen**.
   Nur damit können die GitHub-Default-Branch-Trigger und sicheren Controller
   die `dev`-Regeln aktivieren. Während der folgenden Synchronisation ist
   der Issue-Agent bewusst **fail-closed**, also vorübergehend nicht verfügbar.
2. **Danach `main` vollständig nach `dev` integrieren**. Dadurch sind
   alle neuen #109-Controller und Policies zugleich Bestandteil von `dev`.
3. **Erst dann #108 gegen `dev` retargeten**, Diff, Reviews und neue CI
   prüfen und nach Hardware-/UI-Abnahme manuell mergen.
4. Für einen Release: **separater PR `dev` → `main`** mit eigenen
   Freigaben, nie implizit beim Feature-Merge.

### Einmalige Voraussetzung: `dev` sicher aufholen

Am 16.11.2026 ist `dev` von `main` abgewichen:
**46 eigene `dev`-Commits und 276 ausschließlich auf `main`**.

- [ ] [Draft-PR #110: `main` → `dev`](https://github.com/diddip21/knx_to_openhab/pull/110)
  nur als **Konfliktnachweis** verwenden: GitHub meldet `mergeable_state=dirty`.
  **Nicht** auf diesem PR blind „Resolve conflicts“ auswählen: dessen Head
  ist `main` und ein Konflikt-Commit könnte `main` verändern.
- [ ] Die 46 eigenen `dev`-Commits **erhalten**, weder Reset noch Force-Push.
- [ ] **Separaten Integrationsbranch von `dev`** erstellen, `main` hineinmergen,
  echte Konflikte in Code, UI, `config.json` und CI **inhaltlich** auflösen.
  Mit Git/CLI oder einem kontrollierten Cloud-Entwicklungsarbeitsplatz:
  ```bash
  git fetch origin
  git switch -c integration/main-into-dev origin/dev
  git merge --no-ff origin/main
  # Konflikte einzeln prüfen, passende Dateien editieren,
  # dann: git add <geprüfte Dateien> && git commit
  git push -u origin integration/main-into-dev
  ```
- [ ] Einen neuen **Draft-PR `integration/main-into-dev` → `dev`** erstellen.
  Python 3.12/3.13, Black/isort/Flake8/mypy, Playwright, Konfigurations-
  und Generatorregressionen vollständig grün; alle Diff-Konflikte reviewen.
- [ ] Owner reviewed und merged diesen Integrations-PR **manuell** nach `dev`.
  Erst dann den in Konflikt stehenden #110 schließen.
- [ ] Kontrollieren: GitHub-Vergleich `main...dev` muss
  `behind_by = 0` zeigen (`main` ist Vorfahr von `dev`).
  Sind inzwischen weitere Commits auf `main` gelandet, erneut synchronisieren.

**Automatisches Safety-Gate:** Neue Planungs-/Implementierungsjobs **brechen
ab**, solange `dev` nicht alle `main`-Commits enthält. Controller und Agent-
Berechtigungen bleiben auf `main` vertrauenswürdig; OpenCode liest dann die
jeweils aktuelle Codebasis aus `dev`.

## Aktuelle PRs: was tun?

| PR | Ziel | Noch manueller Schritt |
| --- | --- | --- |
| [#108 HomeKit-Feature](https://github.com/diddip21/knx_to_openhab/pull/108) | **`dev`, nach der Synchronisation** | Bis dahin `main` als Base beibehalten, danach Base auf `dev` umstellen, Diff auf nur die HomeKit-Änderungen prüfen, neue CI abwarten |
| [#109 KI-Controller + Self-Repair](https://github.com/diddip21/knx_to_openhab/pull/109) | **`main`** | **ZUERST** CI und Security-Review, danach manuell mergen; `workflow_run` muss auf dem Default-Branch liegen. Erst anschließend `dev` synchronisieren |
| [#110 Branch-Synchronisationskonflikt](https://github.com/diddip21/knx_to_openhab/pull/110) | `dev` | Ein separater Integrationsbranch muss Konflikte lösen; #110 nicht direkt mergen |

Achtung: Auch wenn #108 und #109 bei einem früheren Commit grün waren,
**nach jeder Basisänderung / jedem neuen Commit die Checks neu prüfen**.

## Laufender Ablauf für neue Issues

| Schritt | Automatisch oder manuell? | Nachweis / Stop-Bedingung |
| --- | --- | --- |
| Issue beschreiben und `ai:plan` setzen | **Manuell: Owner** | Akzeptanzkriterien inkl. betroffener Dateien, Default und Testanforderungen |
| OpenCode liest `dev`, erstellt Plan/Rückfragen | **Automatisch** | GitHub-Issue-Kommentar `Plan vN`; kein Paid-Modell |
| `/ai answer ...` beantworten (optional) | **Manuell: Owner** | Neuer Plan braucht erneute Freigabe |
| `/ai approve vN` | **Manuell: Owner** | Bot bestätigt Digest/Version und setzt `ai:approved` |
| `/ai implement vN` | **Manuell: Owner** | Separater expliziter Start, nur freigegebener Dateiscope |
| OpenCode implementiert, Publisher erzeugt Draft-PR → `dev` | **Automatisch** | `dev` enthält `main`; trusted Sicherheitsprüfungen, Branch, Diff und Draft |
| CI (Lint, Py3.12/3.13, Playwright) | **Automatisch** | Alle verpflichtenden Jobs grün, auf *aktueller* Head-SHA |
| Fehlende CI / kaputter CI-Run → max. 2 Self-Repairs für #89 | **Automatisch, nur nach Aktivierung von #109** | Nur Bot-Draft #89 gegen `dev`, eingeschränkte Dateien, bei Erfolg neue CI, sonst HALT |
| Code-Diff, Kommentarthreads, Übersetzungen, Default und Legacy/YAML prüfen | **Manuell: Reviewer** | Alle Findings gelöst / begründet; keine stillen Anpassungen |
| Echte UI-Screenshots zu `docs/screenshots/` hinzufügen | **Manuell oder mit geprüftem Tool** | Bilder enthalten kein Geheimnis; Dateilinks im PR |
| KNX-/HomeKit-Funktionsprüfung mit Testaktor | **Manuell: Owner/Tester** | 0/100 %, Lamellen-Endlage, Zwischenposition, Stop, Rollback dokumentiert |
| Ready for review, Merge des Feature-PR nach `dev` | **Manuell** | Review, Screenshots, Hardware, letzte CI, keine Konflikte |
| Release-PR `dev` → `main` | **Manuell gestartet**, CI automatisch | **Alle** noch nicht veröffentlichten `dev`-Commits prüfen, `VERSION` und `CHANGELOG.md` gemäß `docs/RELEASING.md` vorbereiten, Pflichtreviews und Rollback |
| Merge Release-PR, Smoke-Test, Issue schließen | **Manuell: Owner** | Post-Merge-CI, Funktionsprobe; für Veröffentlichung danach annotierten `v<version>`-Tag bewusst pushen (`Release`-Action prüft Version), Release-Assets/Checksumme prüfen, erst dann Issue schließen |

### Pflicht-Review vor `dev`-Merge

- [ ] Letzter freigegebener Plan stimmt exakt mit dem PR-Inhalt überein
- [ ] PR enthält keine zusätzlichen Actions-, Permission- oder Dependency-Änderungen
- [ ] Alle Pflicht-CI-Jobs (inklusive übersprungener Jobs) erklärt
- [ ] Keine offenen sicherheits-/funktionsrelevanten Reviews
- [ ] Screenshot und echte UI-Speicher-/Reload-Prüfung
- [ ] Legacy-YAML-Semantik identisch bei gleichem HomeKit-Status
- [ ] Eigener KNX-/HomeKit-Test mit einem sicheren Testaktor, oder Merge **blockieren**
- [ ] PR bleibt Draft, bis der Owner bewusst „Ready for review“ auswählt

### Weitere Automatisierung – sicherer nächster Schritt

1. **Read-only Merge-Readiness-Check**, der aktuelle SHA, Plan/Approval, grüne
   Jobs, Review-Threads, Screenshot-Dateien und Hardwareabnahme in einer
   GitHub-Job-Zusammenfassung mit konkreten Gründen auflistet. Fehlende Belege
   sind `OPEN`, niemals `PASS`.
2. **Echte Playwright-Screenshots** automatisch erstellen und als Artefakte
   bereitstellen; nur geprüfte/anonymisierte Belege nach
   `docs/screenshots/` übernehmen.
3. **Automatische Read-only Code-Review-Runde** gegen den freigegebenen
   Plan und den konkreten Diff. Menschliche Reviewer bleiben die letzte Instanz.
4. **Ruleset für `dev`**: PR-Pflicht, Status-Checks, Review und
   Conversation-Resolution erzwingen. Aktuell ist `dev` nicht geschützt.
   Für `main` dasselbe mit strengeren Freigaben; Admin-Settings nur Owner.
5. **Release-Pipeline** als separater, manuell ausgelöster `dev` → `main` PR
   mit Changelog-, Versions- und Rollback-Check. **Kein Auto-Merge**.

Vertiefung, Links und Audit-Protokoll:
[AI_ISSUE_TO_MERGE_RUNBOOK.md](AI_ISSUE_TO_MERGE_RUNBOOK.md).

**Release-Gate:** Das Projekt veröffentlicht nicht automatisch durch einen
Merge auf `main`. Die [Release-Anleitung](RELEASING.md) verlangt
eine manuelle `VERSION`-/Changelog-Vorbereitung und einen
annotierten Tag `v<version>`. Erst dessen Push startet die
`Release`-Action. Eine komplette `dev`→`main`-Integration
übernimmt alle noch fehlenden `dev`-Commits, nicht ausschließlich
HomeKit #89; daher vorher den vollständigen Release-Diff prüfen.

**Wichtige Einschränkung:** Das beschriebene Self-Repair ist noch kein
nachgewiesener End-to-End-Erfolg. Unit-/Guard-Tests prüfen nur Komponenten;
ein echter CI-Fehler → Modellkorrektur → neuer Commit → grüne CI-Lauf muss
separat an einem ungefährlichen, freigegebenen Testfall validiert werden.
