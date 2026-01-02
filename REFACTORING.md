# Code Refactoring - Roadmap

## Ziel
Umstrukturierung des Codes für bessere Wartbarkeit, Testbarkeit und Erweiterbarkeit.

## Neue Struktur

```
knx_to_openhab/
├── src/
│   ├── __init__.py
│   ├── models/
│   │   └── __init__.py          # Datenmodelle (KNXAddress, OpenHABItem, Floor, Room)
│   ├── generators/
│   │   ├── __init__.py
│   │   ├── base_generator.py    # Basis-Klasse für alle Generatoren
│   │   ├── dimmer_generator.py  # Dimmer-spezifische Logik
│   │   ├── rollershutter_generator.py
│   │   ├── heating_generator.py
│   │   ├── switch_generator.py
│   │   └── generic_generator.py # Fallback für unbekannte Typen
│   ├── parsers/
│   │   ├── __init__.py
│   │   └── knx_parser.py        # KNX Project Parsing
│   ├── exporters/
│   │   ├── __init__.py
│   │   └── openhab_exporter.py  # OpenHAB File Export
│   └── utils/
│       ├── __init__.py
│       ├── config_validator.py  # Config Validation
│       └── address_cache.py     # Performance: Caching
├── tests/
│   ├── unit/
│   │   ├── test_dimmer_generator.py
│   │   ├── test_rollershutter_generator.py
│   │   └── test_models.py
│   └── integration/
│       └── test_full_generation.py
├── ets_to_openhab.py           # Legacy (wird schrittweise migriert)
└── config.json
```

## Migration-Strategie

### Phase 1: ✅ Grundstruktur (DONE)
- [x] `src/` Package erstellen
- [x] `src/models/` mit Datenklassen
- [x] `src/generators/base_generator.py` mit gemeinsamer Logik
- [x] `src/generators/dimmer_generator.py` als Beispiel

### Phase 2: Generator-Implementierung
- [x] `rollershutter_generator.py`
- [x] `heating_generator.py`
- [x] `switch_generator.py`
- [x] `generic_generator.py` (für DPST-mappings)
- [x] `scene_generator.py`

### Phase 3: Parser & Exporter
- [x] `knx_parser.py` - Extrahiert Logik aus `knxproject_to_openhab.py`
- [x] `openhab_exporter.py` - Export-Logik aus `ets_to_openhab.py`

### Phase 4: Utilities
- [x] `config_validator.py` - JSON Schema Validation
- [x] `address_cache.py` - Performance-Optimierung

### Phase 5: Integration
- [x] `src/building_generator.py` - Orchestriert alle Generatoren
- [x] Rückwärtskompatibilität mit altem Code
### Phase 6: Testing
- [x] Performance-Benchmarks
### Phase 7: Cleanup
- [x] Legacy-Code entfernen
- [x] Dokumentation aktualisieren
- [x] Migration Guide für Nutzer

## Vorteile der neuen Struktur

### 1. **Separation of Concerns**
- Jeder Generator ist unabhängig
- Einfacher zu testen
- Neue Device-Typen leicht hinzuzufügen

### 2. **Testbarkeit**
```python
# Beispiel Unit Test
def test_dimmer_with_status():
    generator = DimmerGenerator(config, all_addresses)
    result = generator.generate(dimmer_address, dimmer_co)
    assert result['item_type'] == 'Dimmer'
    assert 'status' in result['thing_info']
```

### 3. **Performance**
- Address-Caching verhindert redundante Suchen
- Einmaliges Durchlaufen statt 3x loops

### 4. **Erweiterbarkeit**
```python
# Neuen Generator hinzufügen:
class MyCustomGenerator(BaseDeviceGenerator):
    def can_handle(self, address):
        return address['DatapointType'] == 'DPST-X-Y'
    
    def generate(self, address, co):
        # Custom Logik
        return {...}
```

### 5. **Type Safety**
Mit Dataclasses und Type Hints:
```python
@dataclass
class OpenHABItem:
    name: str
    item_type: str
    label: str
    # IDE kann jetzt Autocomplete machen!
```

## Verwendung (Nach Migration)

```python
from src.generators import (
    DimmerGenerator,
    RollershutterGenerator,
    SwitchGenerator
)
from src.building_generator import BuildingGenerator

# Initialisierung
generators = [
    DimmerGenerator(config, all_addresses),
    RollershutterGenerator(config, all_addresses),
    SwitchGenerator(config, all_addresses),
]

building_gen = BuildingGenerator(config, generators)
items, things, sitemap = building_gen.generate(floors)
```

## Rückwärtskompatibilität

Während der Migration bleibt `ets_to_openhab.py` funktionsfähig:
```python
# Alt (funktioniert weiterhin):
from ets_to_openhab import main
main()

# Neu (nach Migration):
from src.building_generator import generate_openhab_config
generate_openhab_config(knx_project, config)
```

## Status

- **Phase 1**: ✅ Abgeschlossen
- **Phase 2**: ✅ Abgeschlossen- **Ph
- **Phase 3**: ✅ Abgeschlossen
- **Phase 4**: ✅ Abgeschlossen
- **Phase 5**: ✅ Abgeschlossen
- **Phase 6**: ✅ Abgeschlossen
- **Phase 7**: ✅ Abgeschlossen

- **Phase 5**: ✅ Abgeschlossen
Bei Fragen oder Vorschlägen:
1. Issue erstellen
2. PR gegen `refactor/code-restructuring` Branch
3. Tests hinzufügen!
