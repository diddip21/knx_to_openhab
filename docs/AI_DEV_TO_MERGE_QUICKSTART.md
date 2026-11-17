# KI-Workflow: Von Issue und Plan zum sicheren Merge

**Zuletzt geprüft: 17.11.2026.** Dieses Dokument ist eine Checkliste,
kein Echtzeit-Dashboard. Ein PR-Commit und seine GitHub-Checks müssen vor
jedem Merge erneut auf **derselben SHA** geprüft werden.

## Aktueller Stand und Branch-Regeln

- `main` ist der GitHub-**Default-Branch** und enthält die vertrauenswürdigen
  Issue-Kommentar-/`workflow_run`-Controller und Release-Versionen.
- `dev` ist die Integrationsbasis für **KI-Feature-PRs**.
  `main` ist aktuell ein Vorfahr von `dev`; die vorherige
  Branch-Synchronisation ist abgeschlossen.
- [PR #109](https://github.com/diddip21/knx_to_openhab/pull/109)
  (CI-Reparatur) und [PR #110](https://github.com/diddip21/knx_to_openhab/pull/110)
  (Branch-Synchronisation) sind **gemergt**.
- [PR #108](https://github.com/diddip21/knx_to_openhab/pull/108)
  (HomeKit #89) ist **offen, Ready for review, Base `dev`**.
  Ein neuer Codex-P2-Hinweis zur gespeicherten HomeKit-Vorschau wurde
  im PR-Code bearbeitet und braucht erneut grüne CI und Review-Auflösung.
- `dev` und `main` werden von GitHub als **protected** gemeldet.
  Ob alle gewünschten Rules (erforderliche Reviews/Checks, offene Threads,
  Admin-Bypass) aktiv sind, kann unsere GitHub-App nicht vollständig auslesen.
  Das prüft der Owner in **Settings → Rules → Rulesets / Branches**.
- Der abgeschlossene README-Implementierungspilot für Issue #96 wurde aus
  aktiven Workflows entfernt. Sein gemeinsam genutzter
  Freigabe-Controller in `scripts/issue_impl.py` bleibt.

## Schritte von Anfang bis Ende

| Gate | Wer / wie? | Pflichtbeleg |
| --- | --- | --- |
| 1. Issue erstellen und `ai:plan` setzen | **Manuell: Owner** | Ziele, klare Akzeptanzkriterien, keine privaten ETS-Dateien im Issue |
| 2. Plan/Rückfragen mit OpenCode | **Automatisch** auf Code aus `dev` | Geprüfter Plan vN, Test-/Dateiumfang |
| 3. `/ai answer …` (falls Rückfrage) | **Manuell: Owner** | Antworten, ggf. aktualisierter Plan |
| 4. `/ai approve vN` | **Manuell: Owner** | Bot-Bestätigung, gültiger Issue-Digest, `ai:approved` |
| 5. `/ai implement vN` | **Manuell: Owner** | Separater Start, nie implizit durch Approval |
| 6. OpenCode erzeugt Code/Tests | **Automatisch**, nur im genehmigten Dateiscope | Getrennter Publisher, Draft-PR **gegen `dev`**, keine Paid-Modelle |
| 7. CI | **Automatisch** bei PR und auf `dev`/`main`, bei Token-generiertem PR expliziter Dispatch | Lint, Python 3.11/3.12/3.13, Playwright, keine übersprungenen Pflichtgates |
| 8. Reparatur bei roter CI | **Automatisch für #89**, nur im passenden Bot-**Draft** und expliziten CI-Dispatch | Max. zwei isolierte Korrekturen, jedes Mal neue CI; sonst manueller Stopp |
| 9. KI-/Code-Review und Threads | **Automatisches Codex-Review optional, menschliche Review zwingend** | Keine offenen relevanten Findings, Freigabe auf aktueller SHA |
| 10. Echte UI-Screenshots und API/CLI/Legacy/YAML | **Tests plus manuelle Sichtprüfung** | Geprüfte Bilder in `docs/screenshots/`, Semantik/Defaults nachgewiesen |
| 11. KNX-/HomeKit-Abnahme | **Manuell: Owner/Testperson**, reales Gerät | Gerät, Version, 0/100 %, Lamellen/Stop, Rückfallweg und Datum dokumentiert |
| 12. Merge-Readiness-Bericht | **Automatischer read-only Check** nach PR-/Review-Änderungen, zusätzlich manuell startbar | Aktuelle SHA, Approved Plan, CI, Reviews, Threads, Bilder, Owner-Abnahme |
| 13. Feature-PR nach `dev` mergen | **Nur manuell: Owner** | Alle Blocker gelöst, Checks grün, nicht nur ein früherer Commit |
| 14. Release-PR `dev` → `main` | **Manuell gestartet und überprüft**, CI automatisch | Gesamter Release-Diff, `VERSION`, Changelog, Rollback, Reviews |
| 15. Veröffentlichen | **Manuell: Owner** | Annotations-Tag `v<version>`, GitHub Release, SHA-256 und Installations-/Smoke-Test; danach Issue schließen |

**Sicherheitsregel:** Fehlende Evidenz wird `OPEN`, niemals automatisch
`PASS`. Die AI Readiness-Action besitzt ausschließlich Leserechte und darf
weder PRs verändern noch ihre Reviews oder Hardwaretests selbst freigeben.
Sie setzt auch nicht selbst die erforderlichen GitHub-Ruleset-Checks.

## Nur noch bei Issue #89: exakte manuelle Hardwareabnahme

Wenn du die Änderungen an einem echten KNX-Aktor und mit deiner
openHAB-/HomeKit-Version geprüft hast, füge in **PR #108** einen Kommentar
mit **vollständiger aktueller Commit-SHA** und diesen Feldern hinzu:

```text
/ai hardware-accepted <40-stellige aktuelle PR-Commit-SHA>
Datum: YYYY-MM-DD
Aktor: Typ/Modell, ohne private Gruppenadressen
Beobachtung: 0 % / 100 % / Zwischenposition, Lamellenendlage, Stop-Verhalten
Rollback: vorherige Konfiguration gesichert und Rückweg überprüft
```

Dieser Kommentar ist eine **Owner-Erklärung**, keine automatische
Hardware-Messung. Ohne echte Prüfung ist er **nicht** abzugeben.
Nach jedem neuen Code-Commit muss er auf die neue SHA erneuert werden.

## Merge-Readiness ausführen

- Workflow: [AI merge readiness (read-only)](../../actions/workflows/ai-merge-readiness.yml).
- Er prüft passende KI-PRs bei PR-/Review-Änderungen selbst und lässt sich
  über **Run workflow** auf `main` starten (Eingabe: `pr_number`, z.B. `108`).
- Er liefert in seiner GitHub-Job-Summary `PASS`/`OPEN`/`FAIL` pro Gate.
- Er schlägt fehl, solange Nachweise fehlen. Das ist **kein Auto-Merge**;
  ob der Bericht in GitHub als Pflicht-Status verwendet werden kann,
  hängt von deinen Ruleset-Einstellungen ab.

## Was noch nicht vollautomatisch ist

- Andere Issues als #89 haben derzeit **keinen generischen Schreibagenten**;
  #89 ist ein sicher begrenzter Pilot. Die alten #96-Writes sind deaktiviert.
- Ein echter vollständiger Self-Repair-Zyklus (Fehlschlag → KI-Korrektur
  → neuer Commit → grüne CI) ist **noch nicht live nachgewiesen**.
- Der Reparaturagent bearbeitet ausschließlich einen passenden
  **Bot-Draft-PR** und nur wenn die CI per `workflow_dispatch` fehlgeschlagen
  ist; normale rote PR-CI und PRs mit Status *Ready for review* werden
  bewusst **nicht** automatisch verändert.
- Für reale KNX-Hardware kann es keine verlässliche CI-Abkürzung geben.
- Status- und Ruleset-Pflichten müssen vom Owner geprüft werden.

**Release-Details:** [RELEASING.md](RELEASING.md).
**Vertiefung:** [AI_ISSUE_TO_MERGE_RUNBOOK.md](AI_ISSUE_TO_MERGE_RUNBOOK.md).
