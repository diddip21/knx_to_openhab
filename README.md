# KNX → openHAB: aus dem ETS-Projekt zur prüfbaren Konfiguration

Aus einem ETS-Export (`.knxproj`) erzeugt **LogiKNX2HAB** die passenden KNX-Things, Items und eine Sitemap für openHAB. Du siehst das Ergebnis und die Unterschiede zu deiner laufenden Konfiguration, bevor du die generierten Dateien übernimmst. Alternativ lässt sich der Generator per Kommandozeile nutzen.

> [!CAUTION]
> **Dieser Branch ist eine Vorschau, kein freigegebenes Upgrade.** `developer/feature-upgrade` vereint elf PRs. Die Änderungen an Installer und Laufzeitdaten wurden noch nicht mit einer repräsentativen bestehenden Installation samt Wiederherstellung geprüft. Das Setup blockiert deshalb vorhandene Installationen. **Keine produktive Anlage mit diesem Branch aktualisieren.** `main` und bereits installierte Systeme wurden durch diese Arbeit nicht verändert.

## So funktioniert es

1. **ETS-Projekt auswählen:** `.knxproj`, `.knxprojarchive` oder einen passenden JSON-Dump laden; optional vorher die erkannte Gebäudestruktur ansehen.
2. **Ergebnis prüfen:** generierte Dateien, Hinweise zu unvollständigen Zuordnungen und den Diff zur vorhandenen Konfiguration ansehen. Bis hierhin wird nichts nach openHAB übernommen.
3. **Bewusst übernehmen:** Der Deploy-Dialog zeigt die betroffenen Dateien und ihre Änderungen. Erst nach deiner Bestätigung wird eine Sicherung erstellt und die verwaltete Ausgabe übernommen. Bei Bedarf lässt sich eine Sicherung wiederherstellen.

![Dashboard mit Projektauswahl und Jobs](docs/screenshots/feature-upgrade/after-authenticated-dashboard.png)

**Was entsteht?** Standardmäßig `knx.things`, `knx.items` und `knx.sitemap`; je nach Projekt zusätzlich Persistenz- und Regeldateien. Optional kann bei openHAB 5.2 stattdessen eine gemeinsame `yaml/knx.yaml` für Things, Items und Sitemap gewählt werden. **Die bisherige Textausgabe bleibt voreingestellt.** Beide Modellformate dürfen nicht gleichzeitig für dieselben Entitäten geladen werden. [Ausgabeformate und Beispiele](docs/USER_GUIDE.md#openhab-52-yaml-output).

## Welcher Einstieg passt zu dir?

| Situation | Nächster Schritt |
|---|---|
| Du willst erst verstehen, was sich ändert | [Bebilderter Vorher-/Nachher-Vergleich](docs/FEATURE_UPGRADE.md) ansehen; keine Installation nötig. |
| Du benutzt bereits eine produktive Installation | Beim bestehenden Stand bleiben. Für diesen Branch gibt es noch **keinen** freigegebenen Upgrade-Befehl. [Grund und offene Prüfungen](docs/FEATURE_UPGRADE.md#status-für-bestehende-installationen). |
| Du willst den bisherigen `main`-Stand frisch auf einem separaten Gerät installieren | [Installationshinweise](docs/PRODUCTION_GUIDE.md) und Voraussetzungen prüfen. Der `main`-Installer installiert **nicht** diesen Vorschau-Branch. |
| Du möchtest den Vorschau-Branch entwickeln oder in einem Wegwerf-Testsystem prüfen | [Entwickleranleitung](docs/DEVELOPER_GUIDE.md) bzw. [Installer-Hinweise für Testsysteme](installer/README.md) verwenden. |

**Zugriff auf die Weboberfläche:** Nach einer neuen Installation wird ein eigenes Passwort eingerichtet. Standardmäßig ist die Oberfläche nur am Gerät unter `http://127.0.0.1:8085` erreichbar. Von einem anderen Rechner aus verbindet die [Anleitung für Fernzugriff](docs/USER_GUIDE.md#login-and-remote-access) per SSH-Tunnel. Kein gemeinsames Standardpasswort.

## Funktionen im Alltag

- KNX-Adressen und typische Geräte wie Schalter, Dimmer, Rollläden und Thermostate aus ETS-Struktur und DPT erkennen.
- Unbekannte Adressen, fehlende Rückmeldungen und unvollständige Zuordnungen in Berichten prüfen; automatische Platzierung ist optional.
- Auf Wunsch die Gateway-Adresse ausdrücklich vorgeben; ein leeres Feld behält die Erkennung aus ETS bei.
- Verfügbare APT-Paketversionen für openHAB und evcc sehen und ein unterstütztes Paket einzeln aktualisieren. Paketupdates sind eine gesonderte Aktion und gehören nicht zum normalen Deploy.
- Dateien und Unterschiede vor der Übernahme prüfen und eine Sicherung bei Bedarf wiederherstellen. Der Deploy beschränkt sich auf verwaltete Ausgabedateien.

## Für die Kommandozeile

Auf einem **separaten Entwicklungs- oder Testsystem**:

```bash
git clone --branch developer/feature-upgrade https://github.com/diddip21/knx_to_openhab.git
cd knx_to_openhab
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python knxproject_to_openhab.py --file_path MyHouse.knxproj
```

Die Ausgabe landet gemäß `config.json` im Ausgabeverzeichnis. Für den bisherigen Stand stattdessen `main` auschecken. [CLI und Konfiguration](docs/USER_GUIDE.md#command-line-usage).

## Dokumentation

- [Anwenderanleitung](docs/USER_GUIDE.md): Projekt vorbereiten, Ergebnis prüfen, Einstellungen, Probleme lösen.
- [Änderungen mit Vorher/Nachher](docs/FEATURE_UPGRADE.md): Was dieser Branch ändert und was davon bereits nachgewiesen ist.
- [Installation und Betrieb](docs/PRODUCTION_GUIDE.md): Voraussetzungen, Zugriffswege, Sicherungen und Betriebsgrenzen.
- [Technischer Testbericht](docs/FEATURE_UPGRADE_TESTS.md): PR-Umfang, automatisierte Ergebnisse und ausstehende Systemproben.
- [Entwicklung und Beiträge](docs/DEVELOPER_GUIDE.md) · [Contributing](CONTRIBUTING.md).

## Lizenz

[Lizenztext](LICENSE.txt).
