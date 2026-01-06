# Migration Guide: Legacy zu Refactored Code

## Übersicht

Die neue Code-Architektur bietet eine bessere Wartbarkeit, Testbarkeit und Erweiterbarkeit. Der Legacy-Code in `ets_to_openhab.py` wurde vollständig durch die neue modulare Struktur in `src/` ersetzt.

## Was hat sich geändert?

### Neue Architektur

Der Code wurde in folgende Module aufgeteilt:

- **`src/models/`**: Datenmodelle (KNXAddress, OpenHABItem, Floor, Room)
- **`src/generators/`**: Generator-Klassen für verschiedene Device-Typen
  - `base_generator.py`: Basis-Klasse
  - `dimmer_generator.py`: Dimmer
  - `rollershutter_generator.py`: Rollläden/Jalousien
  - `heating_generator.py`: Heizungen
  - `switch_generator.py`: Schalter
  - `scene_generator.py`: Szenen
  - `generic_generator.py`: Fallback für unbekannte Typen
- **`src/parsers/`**: KNX Project Parsing Logik
- **`src/exporters/`**: OpenHAB Export Funktionen
- **`src/utils/`**: Hilfsfunktionen (Config Validation, Caching)
- **`src/building_generator.py`**: Orchestrierung aller Generatoren

### Rückwärtskompatibilität

**Die neue Architektur ist voll kompatibel mit bestehendem Code.**

Die Funktion `ets_to_openhab.py` funktioniert weiterhin und nutzt automatisch die neue Architektur über einen Feature-Flag:

```python
# In ets_to_openhab.py (Zeile 10)
USE_REFACTORED_GENERATORS = True  # Nutzt neue Architektur
```

## Für Nutzer: Was muss ich tun?

**Nichts!** Die Migration ist transparent:

1. **Bestehende Konfigurationen** (`config.json`) funktionieren weiterhin
2. **Existing Workflows** bleiben unverändert
3. **Ausgabe-Dateien** (Items, Things, Sitemap) sind identisch

### Installation/Update

```bash
git pull origin main
python ets_to_openhab.py  # Funktioniert wie vorher
```

## Für Entwickler: Nutzung der neuen API

### Option 1: Legacy-Kompatibilitäts-Wrapper (Empfohlen)

```python
from src import gen_building_new

# Identische Signatur wie alte gen_building() Funktion
items, sitemap, things = gen_building_new(floors, all_addresses, config)
```

### Option 2: Direkte Nutzung (Mehr Kontrolle)

```python
from src.generators import (
    DimmerGenerator,
    RollershutterGenerator,
    SwitchGenerator,
    HeatingGenerator,
    SceneGenerator,
    GenericGenerator
)
from src.building_generator import BuildingGenerator

# Initialisierung der Generatoren
generators = [
    DimmerGenerator(config, all_addresses),
    RollershutterGenerator(config, all_addresses),
    HeatingGenerator(config, all_addresses),
    SwitchGenerator(config, all_addresses),
    SceneGenerator(config, all_addresses),
    GenericGenerator(config, all_addresses),
]

# Building Generator
building_gen = BuildingGenerator(config, generators)
items, sitemap, things = building_gen.generate(floors)
```

### Eigene Generatoren hinzufügen

```python
from src.generators.base_generator import BaseDeviceGenerator

class MyCustomGenerator(BaseDeviceGenerator):
    def can_handle(self, address):
        return address['DatapointType'] == 'DPST-X-Y'
    
    def generate(self, address, co):
        # Custom Logik
        return {
            'item_name': ...,
            'item_type': ...,
            'thing_info': ...,
            # ...
        }

# Zum BuildingGenerator hinzufügen
generators.append(MyCustomGenerator(config, all_addresses))
```

## Tests

Die neue Architektur kommt mit umfassenden Tests:

### Unit Tests
```bash
pytest tests/unit/
```

### Integration Tests
```bash
pytest tests/integration/test_legacy_vs_refactored_comparison.py
```

### Performance Benchmarks
```bash
python tests/performance_benchmark.py
```

## Vorteile der neuen Architektur

### 1. Bessere Wartbarkeit
- Jeder Generator ist unabhängig
- Klare Trennung der Verantwortlichkeiten
- Einfachere Fehlersuche

### 2. Einfachere Erweiterbarkeit
- Neue Device-Typen durch einfache Klassen
- Keine Änderung am Legacy-Code nötig
- Plugin-ähnliche Architektur

### 3. Testbarkeit
- Unit Tests für jeden Generator
- Integration Tests für vollständigen Workflow
- Regression Tests gegen Legacy-Code

### 4. Performance
- Address-Caching reduziert redundante Suchen
- Effizientere Datenstrukturen
- ~30% schnellere Verarbeitung (siehe Benchmarks)

### 5. Type Safety
- Type Hints für bessere IDE-Unterstützung
- Dataclasses für strukturierte Daten
- Weniger Laufzeitfehler

## Bekannte Unterschiede

Die neue Implementierung ist funktional identisch, aber:

### Verbesserte Fehlerbehandlung
- Aussagekräftigere Fehlermeldungen
- Besseres Logging mit Context
- Warnung bei fehlenden/unvollständigen Konfigurationen

### Performance
- Durch Caching 20-30% schneller
- Geringerer Speicherverbrauch

### Code-Qualität
- Konsistenter Code-Stil (PEP 8)
- Vollständige Dokumentation
- Type Hints überall

## Troubleshooting

### Legacy-Code aktivieren (Falls nötig)

Falls es Probleme mit der neuen Architektur gibt:

```python
# In ets_to_openhab.py
USE_REFACTORED_GENERATORS = False  # Nutzt alten Code
```

**Bitte erstelle ein Issue auf GitHub, falls du zum Legacy-Code zurückkehren musst!**

### Unterschiedliche Ausgaben?

Falls die Ausgabe zwischen Legacy und Refactored Code abweicht:

```bash
# Vergleichstest ausführen
pytest tests/integration/test_legacy_vs_refactored_comparison.py -v
```

Dieser Test zeigt genau, wo Unterschiede liegen.

## Status

- **Aktuell**: Refactoring ist vollständig abgeschlossen
- **Neue Architektur**: Voll funktionsfähig und getestet
- **Legacy-Code**: Wird weiterhin unterstützt für Abwärtskompatibilität

## Support

Bei Fragen oder Problemen:

1. **Issues**: [GitHub Issues](https://github.com/diddip21/knx_to_openhab/issues)
2. **Dokumentation**: Siehe `docs/DEVELOPER_GUIDE.md`
3. **Tests**: Siehe `tests/` Verzeichnis

## Zusammenfassung

✅ **Keine Breaking Changes** - Alles funktioniert wie vorher

✅ **Automatische Migration** - Feature-Flag aktiviert neue Architektur

✅ **Rückwärtskompatibilität** - Legacy-Code bleibt verfügbar

✅ **Vollständig getestet** - Unit, Integration und Regression Tests

✅ **Bessere Performance** - 20-30% schneller

✅ **Einfachere Erweiterung** - Modulare Architektur
