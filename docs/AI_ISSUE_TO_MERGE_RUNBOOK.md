# Runbook: Vom GitHub-Issue bis zum geprüften Merge

> **E2E-Audit am 17.11.2026** – [Issue #89](https://github.com/diddip21/knx_to_openhab/issues/89),
> [Feature-PR #108](https://github.com/diddip21/knx_to_openhab/pull/108).
> Immer den aktuellen HEAD und die tatsächlichen neuesten CI-Läufe prüfen.
> [#109](https://github.com/diddip21/knx_to_openhab/pull/109) ist nach
> `main` gemergt, [#110](https://github.com/diddip21/knx_to_openhab/pull/110)
> hat `main` nach `dev` synchronisiert. Nach Merge von
> [#115](https://github.com/diddip21/knx_to_openhab/pull/115) nach
> `main` ist die Synchronisation erneut zu prüfen.
> #108 ist auf `dev` gerichtet und **Ready for review**; die neue
> Codex-P2-Anmerkung zur HomeKit-Vorschau muss auf der aktuellen SHA erneut
> geprüft und der Inline-Thread aufgelöst werden.
>
> **Grüne CI ≠ fachlich geprüft ≠ freigegeben ≠ gemergt.**
> Ein KNX-Hardwaretest ist **kein verpflichtendes Merge-Gate** und kein
> Bestandteil des Software-Readiness-Berichts. Ohne einen realen Test wird
> keine KNX-/Apple-Home-Hardwarefunktion als verifiziert bezeichnet.
> Ein vollständiger automatischer KI-Reparaturzyklus wurde noch nicht
> Ende-zu-Ende nachgewiesen.

## 1. Rollen, Zuständigkeiten und Grenzen

| Rolle | Was darf sie? | Was nicht? |
| --- | --- | --- |
| Repository-Owner | Issue konkretisieren, Plan freigeben, Implementierung auslösen, Software-Readiness prüfen, Merge entscheiden | Keine Freigabe nur aufgrund des KI-Texts |
| OpenCode + Superpowers | Freigegebenes Issue lesen, Plan erzeugen, begrenzte Codeänderungen und Reparaturen vorschlagen | Nicht eigenständig `main` ändern oder mergen; keine Paid-Modelle |
| Getrennter GitHub-Publisher | Freigaben und Pfade revalidieren, Draft-PR erstellen oder erlaubten PR-Branch aktualisieren | Generierten Code ausführen, Prüfungen umgehen oder `main` ändern |
| GitHub CI | Lint, Core-Python 3.11/3.12/3.13, UI/Playwright und Guard-Tests ausführen | Echtes KNX-Gerät oder Apple Home validieren |
| Menschlicher Reviewer | Diff, Kompatibilität, Testergebnisse, UI und Hinweise prüfen | Nicht durch ein KI-Review ersetzen |

Nur die **exakte Issue-#89-Planversion v2** ist durch die vorhandene
Automatisierung freigegeben. Der abgeschlossene #96-Dokumentationspilot wurde aus aktiven Actions entfernt; seine gemeinsamen Freigabefunktionen bleiben bestehen.
Neue Issues brauchen eigene Scope-/Dateifreigaben und einen neuen,
sicherheitsgeprüften Implementierungsweg.

## 2. Nachweis-Kette: aktueller Stand

| Nr. | Phase / Gate | Trigger / Verantwortlich | Nachweis (konkret) | Status |
| --- | --- | --- | --- | --- |
| 1 | Issue & Scope | Owner erstellt Issue, setzt `ai:plan` | [Issue #89](https://github.com/diddip21/knx_to_openhab/issues/89) | ✅ Erledigt |
| 2 | Planung und Rückfragen | `OpenCode issue planner` erzeugt Version; Owner antwortet mit `/ai answer …` | [Plan v2 in #89](https://github.com/diddip21/knx_to_openhab/issues/89#issuecomment-6918835748) | ✅ Erledigt |
| 3 | Planfreigabe | Owner: `/ai approve v2`, Bot bestätigt; Labels `ai:plan`, `ai:approved` | [Owner-Freigabe](https://github.com/diddip21/knx_to_openhab/issues/89#issuecomment-6919313624); [Bestätigung](https://github.com/diddip21/knx_to_openhab/issues/89#issuecomment-6919319227) | ✅ Erledigt |
| 4 | Ausdrücklicher Implementierungsbefehl | Owner: `/ai implement v2` | [Auslöser](https://github.com/diddip21/knx_to_openhab/issues/89#issuecomment-6920334364) | ✅ Erledigt |
| 5 | Free-Model-Router, Agent, Publisher | CI liest Approval, wählt nur geprüfte Free-Modelle, beschränkt Dateien und publiziert Draft-PR | [Implementierungslauf](https://github.com/diddip21/knx_to_openhab/actions/runs/43893665720) | ✅ Durchlaufen |
| 6 | Draft-PR statt Direktänderung | Publisher erzeugt PR, keine Änderungen an `main` | [Feature-PR #108](https://github.com/diddip21/knx_to_openhab/pull/108) | ✅ Erledigt |
| 7 | CI auf *aktueller* Head-SHA | GitHub: Black, isort, Flake8, mypy, Core 3.11/3.12/3.13, Playwright | Nach der Codex-P2-Korrektur auf #108 erneut verifizieren; alte grüne Runs zählen **nicht** für neue Commits | ⏳ Neue CI nötig / laufend |
| 8 | Automatische CI-Reparatur | Nur genehmigter Bot-**Draft** gegen dev und explizit fehlgeschlagene CI, max. 2 Reparaturversuche | [#109 gemergt](https://github.com/diddip21/knx_to_openhab/pull/109), Unit-/Guard-Tests grün | ⚠️ Aktiviert, echter Live-Selbstkorrekturlauf noch nicht nachgewiesen |
| 9 | Code-/Sicherheitsreview | Reviewer untersucht PR-Diff und Findings, später erneut auf aktueller SHA | [Neues P2-Finding](https://github.com/diddip21/knx_to_openhab/pull/108#discussion_r4601217188) mit offenem Thread; der Owner muss aktualisierten Code prüfen | ⬜ Offen |
| 10 | UI-Belege | Drei reale HomeKit-Einstellungszustände in docs/screenshots/ | PR #108 enthält Default/Enabled/Disabled-Screenshots | ⚠️ Dateien vorhanden, menschliche Sichtprüfung noch erforderlich |
| 11 | Funktionsabnahme | Realitätsnahe Legacy-/YAML-/UI-/CLI-/API-Tests und Manualreview | Software-Review berichtet Ergebnisse; nach Codefix erneut prüfen | ⬜ Zu bestätigen |
| 12 | Ready for review & Feature-Merge | Nur Owner nach allen Software-Gates | #108 ist Ready for review; kein Merge erfolgt | ⚠️ Review-Status gesetzt, Freigabe offen |
| 13 | Release und Nach-Merge-Validierung | Separater PR dev→main, CI, Version/Changelog/annotierter Tag, Smoke | [RELEASING.md](RELEASING.md) | ⬜ Offen |

**Wichtig:** Step 8 wurde durch die Tests des Routers und des
`ci_repair.py`-Validators nur **teilweise** nachgewiesen. Ein tatsächlicher
Fehlschlag → Analyse → KI-Korrektur → neuer Commit → grüne CI wurde noch
nicht live ausgeführt. Keinen Fehler künstlich in den Feature-PR einbauen,
nur um diese Schleife zu demonstrieren.

## 3. Konkrete manuelle Abnahme von HomeKit #89

Diese Liste ist **vor dem Merge von #108** im PR vollständig abzuhaken.
Jeder Haken braucht Datum, Prüfer und ein verlinktes Ergebnis oder eine
nachvollziehbare Anmerkung.

- [ ] **UI-Screenshots:** Echte Einstellungen im General-Tab in
  `docs/screenshots/`: ETS-Automatik und erzwungen ein/aus,
  `sendUpDownForExtents`, `stop`, `stopSameDirection`. Keine Passwörter,
  Zugangsdaten, internen Adressen oder Bewohnerinformationen zeigen.
- [ ] **Speichern/Laden:** Jeden HomeKit-Modus wechseln, speichern,
  neuladen; explizites `false` bleibt erhalten und andere
  Konfigurationsfelder bleiben unverändert.
- [ ] **Wirksamkeit:** Die UI steuert den **nächsten Generierungs-/Reprocess-Lauf**;
  das ist **kein unmittelbares Umschalten einer bereits laufenden
  openHAB-HomeKit-Integration**. Effektiven Status in Preview und Job
  überprüfen, anschließend generieren/deployen.
- [ ] **Default (HomeKit aktiv):** Ohne den Konfigurationsschlüssel steht
  `sendUpDownForExtents="true"` am effektiven `WindowCovering`-
  Equipment-Group-Metadatum, mit korrektem `Instance`.
- [ ] **Opt-out:** Bei `homekit_rollershutter_sendUpDownForExtents=false`
  wird die Option tatsächlich weggelassen. Keine doppelten
  `[...][...]`-Parameterlisten.
- [ ] **Stop-Optionen:** `stop` und `stopSameDirection` unabhängig,
  beide standardmäßig aus; nur aktivierte Optionen erscheinen.
- [ ] **Datenformate:** Für dasselbe ETS-Projekt Legacy-`.items` und
  openHAB-5.2-YAML generieren und relevante HomeKit-Metadaten
  **semantisch** vergleichen (nicht nur Textvergleich).
- [ ] **Datenpfade:** Prüfen, ob Web-UI, API, Vorschau, Job, CLI den
  ETS-Default und Override gleich interpretieren; die richtigen
  Items/Gruppen/Lamellen-Instanzen werden erzeugt.
- [ ] **Regression:** Die drei bestehenden Golden-Projekte
  (`Charne`, `UploadJson`, `Mini`) vergleichen; bei Differenzen
  Abweichungen begründen. Änderungen an anderen Geräten/KNX-Kanälen
  dürfen nicht unbemerkt eintreten.
- [ ] **Reviews:** Sämtliche Inline-Threads und allgemeinen Kommentare
  in #108 und #109 lesen; alle relevanten Findings beheben oder
  dokumentiert zurückweisen. Danach ggf. erneut reviewen lassen.

### Vorlage für den manuellen Abnahme-Kommentar in #108

```text
HomeKit #89 – manuelle Abnahme
PR-Commit: <vollständige SHA>
Prüfer/Datum: <Name, Datum>
openHAB-Version: <Version>
Web-UI (ETS/An/Aus + Save/Reload): PASS / FAIL / NICHT GEPRÜFT
Legacy-YAML-Metadaten-Gleichheit: PASS / FAIL / NICHT GEPRÜFT
Optionen/default false/Stop/Instance: PASS / FAIL / NICHT GEPRÜFT
Screenshots in docs/screenshots/: <Datei-/PR-Link>
Bemerkungen/offene Punkte: <...>
Freigabe zum Merge: JA / NEIN
```

**Kein Merge bei FAIL oder NICHT GEPRÜFT in einem verpflichtenden Software-Gate.**
Ein realer Hardwaretest gehört nicht zur Merge-Readiness; ohne ihn darf keine
Aussage über erfolgreich geprüfte KNX-/Apple-Home-Hardware getroffen werden.

## 4. Automatische Prüf- und Reparaturschleife

```text
Issue + ai:plan
    |
  Plan vN <-- /ai answer ... (optional)
    |
  /ai approve vN (nur Owner, Digest-/Versionsprüfung)
    |
  /ai implement vN (separater Owner-Befehl)
    |
  Free-Model-Router -> eingeschränkter OpenCode-Agent
    |
  getrennter Publisher -> Draft-PR
    |
  expliziter workflow_dispatch CI / push- und PR-Checks
    (Feature-PR-Base: dev, trusted Workflow-Definition: main)
    |
    +-- CI rot --> [nur approved issue89 Bot-Draft & Dispatch]
    |                 -> Reparatur #1 (nur erlaubte Dateien)
    |                 -> neuer CI-Lauf
    |                 -> ggf. Reparatur #2 / erneute CI
    |                 -> danach HALT, menschlich entscheiden
    |
    +-- CI grün --> Code-/Sicherheitsreview
                      -> echte UI-Screenshots + Funktionsprüfung
                      -> Owner setzt Draft auf Ready for Review
                      -> Owner merged Feature nach dev
                      -> Release-PR dev → main (manuell)
                      -> CI/Smoke auf main
                      -> Issue schließen nach belegter Abnahme
```

**Stop-Bedingungen:** Owner-Approval fehlt/wurde widerrufen, neuere
Planversion, Issue-Digest geändert, PR-Head entspricht nicht fehlerhaftem
CI-Commit, Branch aus fremdem Repo, andere Dateipfade, übergroßer Diff,
fehlende kostenlose Modelle, max. zwei Reparaturversuche, Rot in
Pflichtchecks, offene verpflichtende Reviews/Abnahme.

GitHub Actions durch `GITHUB_TOKEN` angelegte PRs starten nicht
notwendigerweise die üblichen PR-Workflows. Der Publisher nutzt deshalb
den **expliziten CI-`workflow_dispatch`**. Vor Freigaben immer prüfen,
dass die **letzte Head-SHA**, nicht nur ein älterer grüner Run, geprüft
wurde.

## 5. Aktuelle Schritte bis zum Merge

1. **PR #108: Codex-P2-Befund prüfen.** Das gespeicherte
   `homekit_enabled` muss sofort in beiden Vorschau-APIs gelten, auch
   wenn das Generatormodul im Flask-Prozess noch alte Config hält.
   Regressionstest speichern → Vorschau prüfen, CI zur neuesten SHA.
2. **Inline-Thread und Review klären.** Review-Kommentar des Codex
   im PR lesen, Änderung beurteilen, ggf. erneut Review starten und
   den Thread **erst nach bestätigtem Fix** auflösen.
3. **Reale UI-Screenshots prüfen.** Dateien unter
   `docs/screenshots/` sind im PR vorhanden; Passwörter/
   Adressen dürfen nicht enthalten sein.
4. **Readiness-Check** über
   [AI merge readiness](https://github.com/diddip21/knx_to_openhab/actions/workflows/ai-merge-readiness.yml)
   auf `main` mit PR-Nummer `108` starten. Der Bericht verifiziert
   Branch, aktuellen CI-Stand, Plan, Approval, Review, Threads,
   Screenshots. Er ist **read-only**
   und meldet fehlende Nachweise als `OPEN`.
5. **Owner entscheidet**, dann manueller Merge von #108 nach
   `dev`. Kein Agent hat Merge-Erlaubnis.
6. **Release separat:** Geprüfter PR `dev` → `main`,
   vollständiger Release-Diff, `VERSION`, Changelog,
   annotierter Tag und GitHub-Release mit Checksumme.
   Zuletzt einen Post-Merge-Smoke-Test dokumentieren und erst danach
   Issue #89 schließen.

**Aktuelle Architektur:** `main` liefert die vertrauenswürdigen
Issue- und CI-Reparatur-Workflows, `dev` ist der Feature-Basisbranch.
GitHub meldet beide Branches als geschützt; einzelne Ruleset-Pflichten
können nur der Owner in *Settings → Rules* vollständig bestätigen.

## 6. Verbesserungen für die nächste Automatisierungsstufe

**Stand 17.11.2026:** Der read-only Merge-Readiness-Check wurde mit
PR #115 nach `main` gemergt. Die Entfernung des Hardware-Gates wird
als separater, reviewbarer Infrastruktur-PR umgesetzt. Der ältere Workflow/Agent für README-Issue #96 wurde deaktiviert,
die Freigabe-/Digest-Bibliothek bleibt für die aktiven Agenten bestehen.
Die CI-Push-Trigger sind auf `main` und `dev` begrenzt, PR- und
explizite Bot-Dispatch-Tests bleiben. OpenCode CLI ist versionsgebunden.
Ein echter Repair-E2E-Lauf ist weiterhin offen.


| Priorität | Vorschlag | Automatisch / manuell | Status |
| --- | --- | --- | --- |
| P0 | **Read-only Flow-Audit** pro AI-PR: aktuelle Head-SHA, Issue/Plan/Approval, CI, Reviews, Screenshotdateien und offene Gates als maschinenlesbare Summary | Automatisch; Reviewentscheidung bleibt menschlich | ✅ Mit #115 implementiert |
| P0 | **Verpflichtende Schutzregeln** für `main`: PR erforderlich, kritische Checks grün, 1 unabhängiges Review, offene Threads erledigt; Admin-Berechtigungen prüfen | GitHub-Branch-Rules/Rulesets | ⚠️ Das sichtbare Ruleset `protect main` blockiert Löschen/Force-Push; Review-/CI-Pflicht daraus **nicht** belegt |
| P1 | **Playwright-Screenshot-Artefakte** für HomeKit-UI inkl. DE/EN und drei Modi automatisch erzeugen, Datenschutz-/Inhaltsprüfung; zum PR verlinken oder geprüfte Dateien nach `docs/screenshots/` übernehmen | Automatisch erstellte Belege, menschlich freigegeben | ⬜ Noch nicht implementiert |
| P1 | **Read-only Code-Review-Agent** nach grüner CI prüft Diff, AGENTS, Plan, Safety, Golden/Legacy/YAML und schreibt Findings ohne Schreibrechte | Automatisch; Human-Review bleibt erforderlich | ⬜ Noch nicht implementiert |
| P1 | **Merge-Readiness-Bericht** als PR-Kommentar/Check mit Grün/Gelb/Rot, konkretem Blocker und Links; keine stillen PASSs bei fehlenden Daten | Automatisch; Merge bleibt manuell | ⬜ Noch nicht implementiert |
| P2 | **Post-Merge-Recheck**: neue CI auf `main`, Release-/Changelog-Notiz, Issue erst nach Software-Abnahme schließen | Größtenteils automatisch; Merge und Freigabe manuell | ⬜ Noch nicht implementiert |
| P2 | **Generischer, policy-gesteuerter Implementierungsagent** für weitere Issues mit separater Owner-Freigabe des genauen Dateiscopes und Budgets | Automatisch innerhalb des genehmigten Scopes | ⬜ Aktuell nur #89 / #96 Piloten |

### Branchschutzbefund vom 17.11.2026

GitHub markiert nun **`main` und `dev` als geschützt**. Über die App
sind die exakten individuellen Review-/Required-Status-Checks weiterhin
nicht lesbar (HTTP 403). Das lesbare Ruleset `protect main` schützt
vor Löschung und Force-Push, zeigt aber nicht den ganzen Branchschutz.
**Manuelle Kontrolle durch den Owner in Settings → Rules ist nötig**.
Keine pauschale Merge-Freigabe allein aus dem Protected-Flag.

## 7. Wiederkehrende E2E-Audit-Routine für JEDEN neuen AI-PR

Vor Abschluss jedes Arbeitsschritts, vor `Ready for review`, vor Merge
und **nach jedem neuen Commit**:

1. **Aktuelle PR-Head-SHA** und Basisbranch feststellen; eventuelle
   neue Commits machen frühere CI-/Review-Belege potenziell veraltet.
2. Issue und letzte **unveränderte**, vom Owner genehmigte Planversion
   mit PR verknüpfen; Owner-Aktion statt Bot-Selbstfreigabe belegen.
3. Kontinuierliche Kette `Issue → Plan → Approval → Implementation →
   Draft-PR → CI → ggf. Repair → Review → Merge →
   post-merge CI` auf Lücken prüfen und für jede Phase
   `PASS`, `FAIL`, `OPEN` oder `N/A mit Begründung` notieren.
4. Alle Reviews, offenen Threads, CI-Jobs (auch übersprungen),
   Screenshots und manuellen Belege einbeziehen.
5. Fehlende Nachweise **offen** lassen, keine Haken aus einer
   erfolgreichen GitHub Action ableiten. Keine Merges durch einen
   automatischen Agenten.
6. Den Status im PR-Kommentar/Runbook mit **Datum, konkretem Commit,
   Links, aktuellem Blocker und nächstem Verantwortlichen**
   aktualisieren.

So bleibt das Runbook nachvollziehbar, selbst wenn GitHub-Actions-Runs,
Modellverfügbarkeit und Freigaben sich später ändern.
