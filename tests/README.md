# Testing Guide for knx_to_openhab

Dieses Repository enthält automatisierte Tests, die sicherstellen, dass die Anwendung auf verschiedenen Plattformen (insbesondere Raspberry Pi mit DietPi) zuverlässig funktioniert.

## Test-Struktur

```
tests/
├── conftest.py              # Gemeinsame pytest fixtures
├── unit/                    # Unit-Tests für einzelne Funktionen
├── integration/             # Integrationstests
├── ui/                      # UI-Tests mit Playwright
│   └── test_web_interface.py
├── fixtures/                # Test-Daten
└── README.md               # Diese Datei
```

## Voraussetzungen

### Basis-Installation
```bash
pip install -r requirements.txt
pip install -r requirements-dev.txt
```

### Für UI-Tests
```bash
playwright install chromium
```

## Tests ausführen

### Alle Tests
```bash
pytest
```

### Nur Unit-Tests
```bash
pytest tests/unit/ -v
```

### Nur Integration-Tests
```bash
pytest tests/integration/ -v
```

### Nur UI-Tests (Web-Server muss laufen!)
```bash
# Terminal 1: Starte Web-Server
cd web_ui/backend
python app.py

# Terminal 2: Führe UI-Tests aus
pytest tests/ui/ -v
```

### Tests mit Coverage
```bash
pytest --cov=. --cov-report=html
# Öffne htmlcov/index.html im Browser
```

### Spezifische Tests
```bash
# Nach Namen filtern
pytest -k "test_login"

# Nur Tests mit bestimmtem Marker
pytest -m unit
pytest -m integration
pytest -m ui
```

## CI/CD Pipeline

Die Tests laufen automatisch bei jedem Push über GitHub Actions:

- ✅ Multi-Platform (Ubuntu, Windows)
- ✅ Mehrere Python-Versionen (3.10, 3.11)
- ✅ ARM64-Kompatibilität (Raspberry Pi Simulation)
- ✅ Installation-Tests

Status: [![CI Tests](https://github.com/diddip21/knx_to_openhab/workflows/CI%20Tests/badge.svg)](https://github.com/diddip21/knx_to_openhab/actions)

## Lokales Testen auf ARM-Architektur

### Mit Docker
```bash
# ARM64 simulieren mit QEMU
docker buildx build --platform linux/arm64 -f Dockerfile.test -t knx-test:arm64 .
docker run --platform linux/arm64 knx-test:arm64
```

### Auf echtem Raspberry Pi
```bash
# Via SSH auf den Pi
ssh pi@raspberrypi.local

# Repository klonen
git clone https://github.com/diddip21/knx_to_openhab.git
cd knx_to_openhab

# Dependencies installieren
pip install -r requirements.txt
pip install pytest

# Tests ausführen
pytest -v
```

## Neue Tests schreiben

### Unit-Test Beispiel
```python
# tests/unit/test_example.py
import pytest

def test_example_function():
    """Test description."""
    result = your_function()
    assert result == expected_value
```

### UI-Test Beispiel
```python
# tests/ui/test_example.py
import pytest
from playwright.sync_api import Page

@pytest.mark.ui
@pytest.mark.requires_server
def test_page_loads(page: Page):
    """Test that page loads correctly."""
    page.goto("http://localhost:8085")
    assert "KNX" in page.title()
```

## Troubleshooting

### Tests finden keine Module
```bash
# Stelle sicher, dass pytest.ini vorhanden ist
# Oder exportiere PYTHONPATH
export PYTHONPATH=.
pytest
```

### UI-Tests schlagen fehl
```bash
# Überprüfe, ob Web-Server läuft
curl http://localhost:8085

# Playwright Browser neu installieren
playwright install --force chromium
```

### ARM-Tests funktionieren nicht
```bash
# QEMU installieren (Linux)
sudo apt-get install qemu-user-static

# Docker Buildx einrichten
docker buildx create --use
```

## Best Practices

1. **Isolation**: Jeder Test sollte unabhängig sein
2. **Fixtures verwenden**: Nutze conftest.py für gemeinsame Setup-Logik
3. **Markers**: Verwende `@pytest.mark.ui`, `@pytest.mark.slow` etc.
4. **Beschreibungen**: Docstrings für jeden Test
5. **Coverage**: Strebe mindestens 80% an

## Support

Bei Problemen:
1. Überprüfe [GitHub Actions Logs](https://github.com/diddip21/knx_to_openhab/actions)
2. Erstelle ein Issue mit Test-Logs
3. Lokale Debug-Ausgabe: `pytest -vv --tb=long`
