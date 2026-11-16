# Runbook: Vom GitHub-Issue bis zum geprüften Merge

> Status: Pilot für [Issue #89](https://github.com/diddip21/knx_to_openhab/issues/89).
> Stand der E2E-Prüfung: **16.11.2026**. PR #108, #109 und der
> neue Entwicklungs-Synchronisations-PR #110 müssen anhand ihrer
> **jeweils aktuellen HEAD-SHA** überprüft werden. Das ist eine
> Momentaufnahme, kein garantiert aktueller Status.
>
> **Merksatz:** Grüne CI ≠ fachlich geprüft ≠ freigegeben ≠ gemergt.
>
> **Aktuelle Blockade:** `dev` besitzt 46 eigene, `main` 276 eigene
> Commits; Draft-PR [#110 (`main` → `dev`)](https://github.com/diddip21/knx_to_openhab/pull/110)
> ist wegen Konflikten **nicht mergebar**. Vor dem Retargeting von
> [#108](https://github.com/diddip21/knx_to_openhab/pull/108) bitte den
> [kompakten dev-Quickstart](AI_DEV_TO_MERGE_QUICKSTART.md) abarbeiten.
> Niemals `dev` auf `main` zurücksetzen oder Konflikte am `main`-Head lösen.

## 1. Rollen, Zuständigkeiten und Grenzen

| Rolle | Was darf sie? | Was nicht? |
| --- | --- | --- |
| Repository-Owner | Issue konkretisieren, Plan freigeben, Implementierung auslösen, Hardware abnehmen, Merge entscheiden | Keine Freigabe nur aufgrund des KI-Texts |
| OpenCode + Superpowers | Freigegebenes Issue lesen, Plan erzeugen, begrenzte Codeänderungen und Reparaturen vorschlagen | Nicht eigenständig `main` ändern oder mergen; keine Paid-Modelle |
| Getrennter GitHub-Publisher | Freigaben und Pfade revalidieren, Draft-PR erstellen oder erlaubten PR-Branch aktualisieren | Generierten Code ausführen, Prüfungen umgehen oder `main` ändern |
| GitHub CI | Lint, Core-Python 3.12/3.13, UI/Playwright und Guard-Tests ausführen | Echtes KNX-Gerät oder Apple Home validieren |
| Menschlicher Reviewer | Diff, Kompatibilität, Testergebnisse, UI und Hinweise prüfen | Nicht durch ein KI-Review ersetzen |
| Hardware-Tester | Endlagen/Lamellen und Rückweg mit realem KNX-Aktor prüfen | Keinen Hardwareerfolg ohne Protokoll behaupten |

Nur die **exakte Issue-#89-Planversion v2** ist durch die vorhandene
Automatisierung freigegeben. Der #96-Dokumentationspilot bleibt separat.
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
| 7 | CI auf *aktuellem* Commit | GitHub: Black, isort, Flake8, mypy, Core 3.12/3.13, UI | [#108 CI 43908602613](https://github.com/diddip21/knx_to_openhab/actions/runs/43908602613): vier Jobs grün auf `7730c7f0` | ✅ Erledigt |
| 8 | Automatische CI-Reparatur | **Nur** fehlgeschlagener, explizit gestarteter CI-Lauf des genehmigten Bot-Drafts **gegen `dev`**; höchstens zwei Versuche | [Infrastruktur-PR #109](https://github.com/diddip21/knx_to_openhab/pull/109), [Guard-Tests](https://github.com/diddip21/knx_to_openhab/actions/runs/43908687141) | ⚠️ Implementiert / noch nicht gemergt / kein Live-E2E-Reparaturtest |
| 9 | Feature-/Sicherheitsreview | Mensch liest alle PR-Kommentare, Diff, Datenflüsse, Tests, Defaults; offene Findings klären | In #108 und #109 zum Prüfzeitpunkt keine formellen Reviews | ⬜ Offen |
| 10 | UI-Belege | Echte, anonymisierte Screenshots der neuen HomeKit-Einstellungen in `docs/screenshots/` einchecken, PR verlinken | PR #108 verändert keine Screenshot-Datei; `AGENTS.md` verlangt sie | ⬜ Offen |
| 11 | Funktionsabnahme | Reales ETS-Projekt; Legacy/YAML, Web-UI, CLI/API, Export und Werte vergleichen | Prüfschritte in Abschnitt 3 | ⬜ Offen |
| 12 | KNX-/Apple-Home-Hardwaretest | Owner testet 0/100 %, Zwischenposition, Lamellen-Endlage, Stop-Schalter, Rollback | Testergebnis mit Gerätemodell, openHAB-Version, Datum, Output-Hinweis | ⬜ Offen |
| 13 | Ready for review & Merge | Owner, nach allen Gates; Merge **manuell** | Draft-Status beider PRs noch aktiv | ⬜ Offen |
| 14 | Nach-Merge-Validierung | CI auf `main`, Smoke-Test in Zielumgebung; erst anschließend Issue schließen | Noch kein Merge | ⬜ Offen |

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
- [ ] **Realgerät:** Mit *einem* Testaktor zunächst 0 %, 100 %,
  Zwischenposition, Pause und Lamellenstellung prüfen. Nachweis, ob
  die Endlage nicht unerwartet die Lamellen verstellt.
  Sicheres Zurückrollen auf vorherige Konfiguration bereitstellen.
- [ ] **Reviews:** Sämtliche Inline-Threads und allgemeinen Kommentare
  in #108 und #109 lesen; alle relevanten Findings beheben oder
  dokumentiert zurückweisen. Danach ggf. erneut reviewen lassen.

### Vorlage für den manuellen Abnahme-Kommentar in #108

```text
HomeKit #89 – manuelle Abnahme
PR-Commit: <vollständige SHA>
Prüfer/Datum: <Name, Datum>
openHAB-Version: <Version>
KNX-/Aktor-Typ (ohne private Adressen): <Typ>
Web-UI (ETS/An/Aus + Save/Reload): PASS / FAIL / NICHT GEPRÜFT
Legacy-YAML-Metadaten-Gleichheit: PASS / FAIL / NICHT GEPRÜFT
Optionen/default false/Stop/Instance: PASS / FAIL / NICHT GEPRÜFT
Screenshots in docs/screenshots/: <Datei-/PR-Link>
Endlagen 0/100 %, Zwischenposition, Lamellen: PASS / FAIL / NICHT GEPRÜFT
Rollback geprobt: PASS / FAIL / NICHT GEPRÜFT
Bemerkungen/offene Punkte: <...>
Freigabe zum Merge: JA / NEIN
```

**Kein Merge bei FAIL oder NICHT GEPRÜFT in einem verpflichtenden Gate.**
Wenn kein reales Gerät verfügbar ist, Abnahme als *offen* kennzeichnen,
aber nicht stillschweigend als bestanden deklarieren.

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
                      -> KNX-Hardwareabnahme
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

## 5. Merge-Reihenfolge, verantwortliche Aktionen

1. **`dev` zuerst mit `main` versöhnen** und die 46
   exklusiven `dev`-Commits erhalten: [#110](https://github.com/diddip21/knx_to_openhab/pull/110)
   ist ein **nicht mergebarer Konfliktnachweis** (Head `main`);
   Konflikte in einem **separaten Integrationsbranch von `dev`**
   lösen und per kontrolliertem PR nach `dev` einbringen.
   Details und Befehle:
   [dev-Quickstart](AI_DEV_TO_MERGE_QUICKSTART.md).
2. **#109 gegen `main` prüfen und mergen**, wenn Security-Review und
   grüne Tests dieses *exakten* Commits vorliegen. Das aktiviert
   die Reparatur für spätere fehlgeschlagene CI-`workflow_dispatch`-
   Läufe des Issue-#89-Drafts; ein bereits grüner Lauf löst keinen
   Reparaturagenten aus.
3. **#108 erst nach synchronisiertem `dev` auf Base `dev`
   retargeten**. Danach die neue Diff-/CI-Matrix prüfen, `main`
   keinesfalls durch diesen PR mergen.
4. **#108 fachlich abnehmen**, fehlende Screenshots ergänzen,
   Generator-Ausgabe/Config real vergleichen und Human-Review abschließen.
5. Nach jedem PR-Commit oder jeder Base-Änderung alle Checks
   noch einmal anhand der Head-SHA
   prüfen, inklusive Screenshot-/Golden-Tests und Kommentaren.
6. Wenn die manuellen Gates dokumentiert sind, Draft-Status von #108
   auf *Ready for review* setzen. **Merge ausschließlich durch Owner**.
7. Erst nach erfolgreich integriertem `dev` einen **separaten
   Release-PR `dev` → `main`** erstellen. Dafür erneut CI,
   Reviews, Rollback-Plan und manuelle Owner-Freigabe verlangen.
8. Nach diesem Release-Merge CI auf `main` und einen sicheren lokalen
   HomeKit-/KNX-Smoke-Test dokumentieren. Erst danach Issue #89
   schließen.

## 6. Verbesserungen für die nächste Automatisierungsstufe

| Priorität | Vorschlag | Automatisch / manuell | Status |
| --- | --- | --- | --- |
| P0 | **Read-only Flow-Audit** pro AI-PR: aktuelle Head-SHA, Issue/Plan/Approval, CI, Reviews, Screenshotdateien und offene Gates als maschinenlesbare Summary | Automatisch; Reviewentscheidung bleibt menschlich | ⬜ Noch nicht implementiert |
| P0 | **Verpflichtende Schutzregeln** für `main`: PR erforderlich, kritische Checks grün, 1 unabhängiges Review, offene Threads erledigt; Admin-Berechtigungen prüfen | GitHub-Branch-Rules/Rulesets | ⚠️ Das sichtbare Ruleset `protect main` blockiert Löschen/Force-Push; Review-/CI-Pflicht daraus **nicht** belegt |
| P1 | **Playwright-Screenshot-Artefakte** für HomeKit-UI inkl. DE/EN und drei Modi automatisch erzeugen, Datenschutz-/Inhaltsprüfung; zum PR verlinken oder geprüfte Dateien nach `docs/screenshots/` übernehmen | Automatisch erstellte Belege, menschlich freigegeben | ⬜ Noch nicht implementiert |
| P1 | **Read-only Code-Review-Agent** nach grüner CI prüft Diff, AGENTS, Plan, Safety, Golden/Legacy/YAML und schreibt Findings ohne Schreibrechte | Automatisch; Human-Review bleibt erforderlich | ⬜ Noch nicht implementiert |
| P1 | **Merge-Readiness-Bericht** als PR-Kommentar/Check mit Grün/Gelb/Rot, konkretem Blocker und Links; keine stillen PASSs bei fehlenden Daten | Automatisch; Merge bleibt manuell | ⬜ Noch nicht implementiert |
| P2 | **Post-Merge-Recheck**: neue CI auf `main`, Release-/Changelog-Notiz, Issue erst nach Abnahme schließen | Größtenteils automatisch; Hardware manuell | ⬜ Noch nicht implementiert |
| P2 | **Generischer, policy-gesteuerter Implementierungsagent** für weitere Issues mit separater Owner-Freigabe des genauen Dateiscopes und Budgets | Automatisch innerhalb des genehmigten Scopes | ⬜ Aktuell nur #89 / #96 Piloten |

### Repo-Schutzbefund vom 16.11.2026

Das aktive, lesbare GitHub-Ruleset **`protect main`** verbietet
Branch-Löschung und Nicht-Fast-Forward-Updates. Es enthält **keine**
eigenen Regeln für Pflicht-Reviews oder Status-Checks. Der separate
Branch-Protection-Endpunkt war mit der aktuellen GitHub-Verbindung
nicht lesbar (HTTP 403); deshalb sind möglicherweise weitere Regeln
vorhanden, aber **nicht nachgewiesen**. Der Owner prüft dies manuell
unter *Settings → Rules → Rulesets* bzw. *Branches*.

## 7. Wiederkehrende E2E-Audit-Routine für JEDEN neuen AI-PR

Vor Abschluss jedes Arbeitsschritts, vor `Ready for review`, vor Merge
und **nach jedem neuen Commit**:

1. **Aktuelle PR-Head-SHA** und Basisbranch feststellen; eventuelle
   neue Commits machen frühere CI-/Review-Belege potenziell veraltet.
2. Issue und letzte **unveränderte**, vom Owner genehmigte Planversion
   mit PR verknüpfen; Owner-Aktion statt Bot-Selbstfreigabe belegen.
3. Kontinuierliche Kette `Issue → Plan → Approval → Implementation →
   Draft-PR → CI → ggf. Repair → Review → Hardware → Merge →
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
