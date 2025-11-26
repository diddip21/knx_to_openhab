# Business Logic Validation in Tests

## Übersicht

Die Tests validieren **zwei Arten** von Business-Logik:

### 1. Implizite Business-Logik (via Golden Files)

**Was wird validiert:**
Die Output-Validierungs-Tests (`test_output_validation.py`) vergleichen die generierten OpenHAB-Dateien Zeile für Zeile mit den Golden Files. Dies validiert **implizit** die gesamte Business-Logik:

#### In `knx.items`:
- ✅ Korrekte Item-Typen (Switch, Dimmer, Rollershutter, etc.)
- ✅ Richtige Gruppenzuordnung (Floor, Room, Equipment)
- ✅ Semantic Tags ([\"Light\"], [\"Blinds\"], etc.)
- ✅ HomeKit/Alexa Metadata
- ✅ Label-Generierung und -Bereinigung
- ✅ Icon-Zuordnung

#### In `knx.things`:
- ✅ Thing-Typ-Zuordnung (switch, dimmer, rollershutter)
- ✅ Gruppenadressen-Verknüpfung
- ✅ Feedback-Adressen (Status-GAs)
- ✅ Zusätzliche Parameter (increaseDecrease, position, etc.)

#### In `knx.sitemap`:
- ✅ Sitemap-Struktur (Floors → Rooms)
- ✅ Widget-Typen (Default, Selection)
- ✅ Visibility-Regeln

#### In `influxdb.persist`:
- ✅ Persistence-Strategien
- ✅ Items mit "influx" Flag

**Beispiel:**
Wenn die Business-Logik entscheidet, dass ein Dimmer mit Schalter kombiniert werden soll, wird dies in der generierten `knx.things` Datei sichtbar:
```
Type dimmer : i_EG_RM1_Licht "..." [ position="1/1/1+<1/1/2", switch="1/1/3+<1/1/4" ]
```
Der Golden File Test stellt sicher, dass diese Entscheidung konsistent bleibt.

### 2. Explizite Business-Logik (via Log-Tests)

**Was wird validiert:**
Die Business-Logik-Tests (`test_business_logic.py`) prüfen **explizit** die Entscheidungsprozesse:

#### Warnungen für unplatzierte Adressen:
```python
test_no_room_found_warnings()
```
- ✅ Prüft, dass Adressen ohne Raum-Zuordnung gewarnt werden
- ✅ Validiert Warning-Level
- ✅ Beispiel: "No Room found for =1.OG +RM6 Wanne_sch_rm"

#### Unvollständige Komponenten:
```python
test_incomplete_dimmer_warnings()
```
- ✅ Prüft Warnungen für Dimmer ohne Status-GA
- ✅ Beispiel: "incomplete dimmer: =EG +RM1 Licht / 1/1/1"

#### Ungenutzte Adressen:
```python
test_unused_addresses_logged()
```
- ✅ Prüft, dass nicht verwendete GAs geloggt werden
- ✅ Beispiel: "unused: 0/0/1: Uhrzeit with type DPST-10-1"

#### Szenen ohne Mapping:
```python
test_scene_without_mapping_logged()
```
- ✅ Prüft Warnungen für Szenen ohne Mapping-Definition
- ✅ Beispiel: "no mapping for scene 0/4/0 Szene"

## Zusammenfassung

| Aspekt | Golden Files | Log-Tests |
|--------|--------------|-----------|
| **Was** | Finales Ergebnis | Entscheidungsprozess |
| **Wie** | Diff-Vergleich | Log-Analyse |
| **Wann** | Nach Generierung | Während Generierung |
| **Beispiel** | "Item hat korrekten Typ" | "Warum wurde dieser Typ gewählt?" |

## Vollständige Business-Logik-Abdeckung

**Ja**, die Business-Logik wird vollständig validiert:

1. **Strukturelle Entscheidungen** → Golden Files
   - Item-Typen, Gruppierungen, Metadata

2. **Prozess-Entscheidungen** → Log-Tests
   - Warnungen, Fehlerbehandlung, Ausnahmen

3. **Daten-Integrität** → Beide
   - Golden Files: Korrekte Ausgabe
   - Log-Tests: Korrekte Verarbeitung

## Beispiel-Szenario

**Szenario:** Ein Dimmer mit unvollständiger Konfiguration

1. **Log-Test validiert:**
   - ⚠️ "incomplete dimmer: =EG +RM1 Licht / 1/1/1" wurde geloggt

2. **Golden File validiert:**
   - ✅ Item wurde NICHT generiert (oder als einfacher Switch)
   - ✅ Konsistentes Verhalten bei zukünftigen Runs

**Beide Tests zusammen** stellen sicher, dass:
- Die Entscheidung dokumentiert ist (Log)
- Das Ergebnis korrekt ist (Golden File)
- Zukünftige Änderungen keine Regression verursachen
