# Code Quality Guide

Dieses Projekt verwendet automatisierte Code-Quality-Checks, um einen konsistenten und wartbaren Code-Standard zu gewährleisten.

## Automatische Checks in CI/CD

Bei jedem Push und Pull Request werden folgende Checks automatisch ausgeführt:

### 1. ✅ Python Syntax Check
- Prüft alle `.py` Dateien auf Syntax-Fehler
- **Muss bestehen** - Pipeline schlägt fehl bei Syntax-Fehlern

### 2. ✅ Flake8 Critical Errors
- Prüft auf kritische Fehler:
  - `E9`: Syntax-Fehler
  - `F63`: Tupel-Fehler
  - `F7`: Syntax-Fehler in Doctests
  - `F82`: Undefined names
- **Muss bestehen** - Pipeline schlägt fehl bei kritischen Fehlern

### 3. ⚠️ Code Formatting (Black)
- Prüft PEP 8 konforme Formatierung
- **Warnung only** - empfohlen zu beheben
- Fix: `black .`

### 4. ⚠️ Import Sorting (isort)
- Prüft alphabetische Sortierung der Imports
- **Warnung only** - empfohlen zu beheben
- Fix: `isort .`

### 5. ⚠️ PEP8 Style Guide
- Prüft PEP 8 Konventionen
- Max. Line Length: 120 Zeichen
- **Warnung only**

### 6. ⚠️ Pylint Code Analysis
- Prüft auf potenzielle Code-Probleme
- **Warnung only**

### 7. ✅ JSON Validation
- Validiert alle `.json` Dateien
- **Muss bestehen** - fehlerhafte JSON-Dateien brechen die Pipeline

### 8. ⚠️ Security Scan (Bandit)
- Sucht nach bekannten Sicherheitsproblemen
- **Warnung only** - sollte aber beachtet werden

### 9. ⚠️ Trailing Whitespace
- Prüft auf Leerzeichen am Zeilenende
- **Warnung only**

## Lokale Code-Checks

### Schnell-Check vor dem Commit

```bash
# Alle Checks auf einmal
chmod +x scripts/check_code.sh
./scripts/check_code.sh
```

### Einzelne Tools verwenden

#### 1. Development-Tools installieren
```bash
pip install -r requirements-dev.txt
```

#### 2. Syntax Check
```bash
python -m py_compile *.py
```

#### 3. Flake8 (vollständiger Check)
```bash
flake8 .
```

#### 4. Code Formatierung mit Black
```bash
# Nur checken
black --check .

# Automatisch formatieren
black .
```

#### 5. Imports sortieren mit isort
```bash
# Nur checken
isort --check-only .

# Automatisch sortieren
isort .
```

#### 6. Security Check
```bash
bandit -r . -ll -x venv,tests
```

#### 7. Type Checking (optional)
```bash
mypy *.py --ignore-missing-imports
```

## Code-Style Konfiguration

### .flake8
Flake8-Konfiguration für das Projekt:
- Max Line Length: 120
- Ignoriert: E203, E501, W503, E402
- Max Complexity: 15

### Black
Standard Black-Formatierung mit 120 Zeichen Line Length.

### isort
Kompatibel mit Black-Formatierung.

## Pre-Commit Hook (optional)

Für automatische Checks vor jedem Commit:

```bash
# 1. pre-commit installieren
pip install pre-commit

# 2. Hook aktivieren
pre-commit install
```

Erstelle `.pre-commit-config.yaml`:
```yaml
repos:
  - repo: https://github.com/psf/black
    rev: 23.12.0
    hooks:
      - id: black
        language_version: python3.11

  - repo: https://github.com/pycqa/isort
    rev: 5.13.0
    hooks:
      - id: isort
        args: ["--profile", "black"]

  - repo: https://github.com/pycqa/flake8
    rev: 6.1.0
    hooks:
      - id: flake8
        args: ["--max-line-length=120"]
```

## Best Practices

### 1. Vor jedem Commit
```bash
# Quick Check
./scripts/check_code.sh

# Code formatieren
black .
isort .
```

### 2. Bei Pull Requests
- Alle kritischen Checks müssen grün sein (✅)
- Warnungen sollten minimiert werden (⚠️)
- Neue Features sollten Tests haben

### 3. Bei neuen Dateien
- Imports am Anfang sortiert
- Docstrings für Funktionen/Klassen
- Type Hints verwenden

### 4. Code Review
- Auf Warnungen achten
- Security-Findings prüfen
- Code-Komplexität beachten

## Troubleshooting

### "flake8: command not found"
```bash
pip install -r requirements-dev.txt
```

### "Black would reformat..."
```bash
black .
```

### "Import order issues"
```bash
isort .
```

### "Bandit findet Sicherheitsprobleme"
Prüfe die Findings und behebe sie oder füge `# nosec` Kommentar hinzu wenn False Positive.

## Siehe auch

- [GitHub Actions Workflow](.github/workflows/ci.yml)
- [Flake8 Config](.flake8)
- [Developer Guide](DEVELOPER_GUIDE.md)
- [Testing Guide](tests/README.md)
