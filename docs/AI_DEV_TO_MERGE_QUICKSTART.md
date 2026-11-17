# KI-Workflow: Von Issue und Plan zum sicheren Merge

**Zuletzt geprüft: 17.11.2026.** Dieses Dokument ist eine Checkliste,
kein Echtzeit-Dashboard. Ein PR-Commit und seine GitHub-Checks müssen vor
jedem Merge erneut auf **derselben SHA** geprüft werden.

## Aktueller Stand und Branch-Regeln

- `main` ist der GitHub-**Default-Branch** und enthält die vertrauenswürdigen
  Issue-Kommentar-/`workflow_run`-Controller und Release-Versionen.
- `dev` ist die Integrationsbasis für **KI-Feature-PRs**.
  Nach neuen Änderungen an `main` (insbesondere PR #115) muss
  `dev` erneut mit `main` synchronisiert werden, bevor der nächste
  genehmigte Implementierungslauf gestartet wird.
- [PR #109](https://github.com/diddip21/knx_to_openhab/pull/109)
  (CI-Reparatur) und [PR #110](https://github.com/diddip21/knx_to_openhab/pull/110)
  (Branch-Synchronisation) sind **gemergt**.
- [PR #115](https://github.com/diddip21/knx_to_openhab/pull/115)
  (bereinigte CI und Merge-Readiness) ist nach `main` gemergt.
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
| 11. Merge-Readiness-Bericht | **Automatischer read-only Check** nach PR-/Review-Änderungen, zusätzlich manuell startbar | Aktuelle SHA, Approved Plan, CI, Reviews, Threads, Bilder |
| 12. Feature-PR nach `dev` mergen | **Nur manuell: Owner** | Alle Software-Blocker gelöst, Checks grün, nicht nur ein früherer Commit |
| 13. Release-PR `dev` → `main` | **Manuell gestartet und überprüft**, CI automatisch | Gesamter Release-Diff, `VERSION`, Changelog, Rollback, Reviews |
| 14. Veröffentlichen | **Manuell: Owner** | Annotations-Tag `v<version>`, GitHub Release, SHA-256 und Installations-/Smoke-Test; danach Issue schließen |

**Sicherheitsregel:** Fehlende Evidenz wird `OPEN`, niemals automatisch
`PASS`. Die AI Readiness-Action besitzt ausschließlich Leserechte und darf
weder PRs verändern noch ihre Reviews oder Hardwaretests selbst freigeben.
Sie setzt auch nicht selbst die erforderlichen GitHub-Ruleset-Checks.

## Geltungsbereich des Prüfberichts

Der Hardwaretest ist **kein Merge-Gate** und wird im
Software-Readiness-Bericht nicht verlangt. Ohne einen Test mit einem echten
KNX-Aktor lässt sich dessen Verhalten mit openHAB/Apple Home
nicht als erfolgreich validiert ausweisen. Die Entscheidung über den
Merge und über einen späteren Hardwaretest bleibt beim Owner.

## Merge-Readiness ausführen

- Workflow: [AI merge readiness (read-only)](https://github.com/diddip21/knx_to_openhab/actions/workflows/ai-merge-readiness.yml).
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
- Der Softwarebericht ersetzt keine Validierung auf realer KNX-Hardware.
- Status- und Ruleset-Pflichten müssen vom Owner geprüft werden.

**Release-Details:** [RELEASING.md](RELEASING.md).
**Vertiefung:** [AI_ISSUE_TO_MERGE_RUNBOOK.md](AI_ISSUE_TO_MERGE_RUNBOOK.md).
