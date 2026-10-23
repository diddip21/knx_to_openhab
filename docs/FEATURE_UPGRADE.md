# Feature Upgrade – integrierter Stand der offenen PRs

**Branch:** `developer/feature-upgrade`  
**Dokumentationsstand:** 23.10.2026  
**Ausgangsbasis:** `main` (`f092abd`)  
**Umfang:** Die elf am 23.10.2026 offenen PRs #33, #35, #37, #39, #42–#48 sind auf diesem Integrationsbranch zusammengeführt. `main` ist davon nicht verändert. PR #39 war zum Prüfzeitpunkt ein Draft. Die Aufnahme hier ist eine Integrationsprüfung und kein Release auf `main`.

Diese Seite erklärt die sichtbaren Änderungen, das Verhalten für Anwender und den Upgrade-Ablauf. Die detaillierte technische Test- und Konfliktübersicht steht im [Integrations-Testbericht](FEATURE_UPGRADE_TESTS.md). Die Sicherheitsdetails sind in der [Upload-Sicherheitsdokumentation](SECURITY_UPLOAD.md), im [Produktionsleitfaden](PRODUCTION_GUIDE.md) und im [Entwicklerleitfaden](DEVELOPER_GUIDE.md) festgehalten.

## Vorher und nachher

### Weboberfläche und Anmeldung

**Vorher:** Auf `main` öffnete sich die KNX-Weboberfläche direkt mit dem Dashboard. Es gab keinen Anmeldebildschirm.

![Vorher: Dashboard ohne vorgeschaltete Anmeldung](screenshots/feature-upgrade/before-main-dashboard.png)

**Nachher:** Die Weboberfläche verlangt eine Anmeldung. Nach erfolgreicher Anmeldung erscheint das Dashboard. Nach Ablauf der Sitzung leitet die Oberfläche zurück zur Anmeldung.

![Nachher: Anmeldeseite](screenshots/feature-upgrade/after-login.png)

![Nachher: angemeldetes Dashboard](screenshots/feature-upgrade/after-authenticated-dashboard.png)

![Nachher: erneute Anmeldung nach Sitzungsablauf](screenshots/feature-upgrade/after-session-expiry.png)

Die Nachher-Aufnahmen stammen aus dem erfolgreichen GitHub-Actions-Lauf für PR #48 (Run 511). Die Bilder zeigen synthetische Testdaten. Das CI-Artefakt enthält Screenshots, kein Video.

### Vorher-/Nachher-Übersicht der sichtbaren Funktionen

| Bereich | Vorher auf `main` | Nachher auf `developer/feature-upgrade` | Bildnachweis |
|---|---|---|---|
| Anmeldung | Das Dashboard war direkt und ohne Anmeldung erreichbar. | Login, geschützte Sitzung und Rückleitung zur Anmeldung nach Sitzungsablauf. | Vorher- und Nachher-Aufnahmen oben. |
| Ausgabeformat | Der Generator bot nur die bisherige Textausgabe. | In den erweiterten Einstellungen ist zusätzlich openHAB-5.2-YAML auswählbar; `legacy` bleibt Standard. | [YAML-Einstellung](screenshots/issue-38-yaml-settings.png) und [Beispielausgabe](screenshots/issue-38-generated-yaml.png). |
| KNX-Gateway | Die Adresse kam aus der ETS-Projekterkennung. | Eine optionale IPv4- oder IPv6-Adresse kann die erkannte Adresse überschreiben. | [Gateway-Einstellung](screenshots/issue-40-gateway-ip-settings.png) und [generierte KNX-Bridge](screenshots/issue-40-generated-knx-things.png). |
| Paketupdates | Version und Update-Status waren in der Weboberfläche nicht sichtbar. | openHAB- und evcc-Paketversionen, APT-Kandidaten und verfügbare Einzelupdates erscheinen im Bereich Dienste. | [Updates verfügbar](screenshots/issue-41-updates-available.png) und [evcc ohne APT-Paket](screenshots/issue-41-no-apt-package.png). |

Die Einstellungs- und Ausgabebilder für YAML, Gateway-IP und Paketupdates stammen aus den automatisierten PR-Läufen mit Beispieldaten. Für diese drei Bereiche gibt es im Repository keine authentische Aufnahme der alten `main`-Oberfläche. Der Vorher-Zustand ist daher als Funktionsvergleich beschrieben; es wird kein altes UI-Bild vorgetäuscht. Die übrigen PRs ändern Sicherheit, Installer, Laufzeitdaten oder Tests und erzeugen keine eigene neue Oberfläche.

### Weitere sichtbare Funktionen

**openHAB-YAML-Ausgabe (PR #39):** Die neue Ausgabeoption ist in den erweiterten Einstellungen sichtbar. Der bisherige Legacy-Renderer bleibt die Voreinstellung.

![YAML-Ausgabeoption](screenshots/issue-38-yaml-settings.png)

**KNX-Gateway-IP (PR #42):** Im Gerätebereich kann optional eine feste Gateway-IP eingetragen werden. Ein leeres Feld lässt die ETS-Erkennung unverändert.

![Gateway-IP-Einstellung](screenshots/issue-40-gateway-ip-settings.png)

**Paketupdates (PR #43):** Im Bereich Dienste erscheinen verfügbare APT-Updates für openHAB und evcc; nicht über APT installierte evcc-Installationen werden als nicht unterstützt angezeigt.

![Verfügbare Paketupdates](screenshots/issue-41-updates-available.png)

## Änderungen und Umgang damit

| PR | Änderung aus Anwendersicht | So wird sie verwendet bzw. worauf zu achten ist |
|---|---|---|
| [#33 – KNX-Upload absichern](https://github.com/diddip21/knx_to_openhab/pull/33) | Uploads werden vor dem Parsen auf erlaubte Dateitypen und Inhalte geprüft. Übergrößen, unsichere Archive und Pfadmanipulation werden abgewiesen. Passwörter aus geschützten Projektdateien bleiben aus Jobdaten und Logs heraus. | Weiterhin `.knxproj`, `.knxprojarchive` oder `.json` hochladen. Bei Ablehnung Dateityp und konfigurierte Größenlimits prüfen. Details: [Upload-Sicherheit](SECURITY_UPLOAD.md). |
| [#35 – Browser-Regressionstests](https://github.com/diddip21/knx_to_openhab/pull/35) | Keine zusätzliche Produktfunktion; die wichtigsten UI-Abläufe werden automatisiert im Browser geprüft. | Anwender müssen nichts umstellen. Die Tests laufen in CI mit Chromium. |
| [#37 – veraltete Testdateien bereinigen](https://github.com/diddip21/knx_to_openhab/pull/37) | Keine Änderung am Produktverhalten. Doppelte und nicht ausgeführte Alt-Testskripte werden entfernt. | Keine Aktion nötig. |
| [#39 – native openHAB-5.2-YAML-Ausgabe](https://github.com/diddip21/knx_to_openhab/pull/39) | Zusätzlich zum bisherigen Textformat kann ein strukturiertes YAML-Modell erzeugt werden. | In Einstellungen → Erweitert das Ausgabeformat auswählen. `legacy` bleibt Standard. YAML nur mit openHAB 5.2 verwenden. Vor einem Wechsel wird eine Sicherung erstellt. Die Formate sollen nicht parallel aktiv sein; der Wechsel nimmt nur die exakt verwalteten, generierten Modell-Dateien der vorherigen Form zurück. `influxdb.persist` und `fenster.rules` bleiben Textdateien. Der Smoke-Test gegen eine laufende openHAB-5.2-Instanz steht noch aus. |
| [#42 – Gateway-IP überschreiben](https://github.com/diddip21/knx_to_openhab/pull/42) | Die Gateway-IP kann für ein KNX-Projekt fest vorgegeben werden. | Im Geräte-Tab IPv4- oder IPv6-Adresse eintragen und speichern. Leer lassen, um die bisherige automatische Erkennung zu nutzen. Ungültige Adressen werden vor der Generierung abgewiesen. |
| [#43 – openHAB/evcc-Paketupdates](https://github.com/diddip21/knx_to_openhab/pull/43) | APT-Version und Kandidat werden in der Weboberfläche angezeigt; Pakete können einzeln aktualisiert werden. | Zuerst Paketlisten prüfen, dann gewünschtes Paket und bestätigte Version aktualisieren. Es wird nur das ausgewählte, bereits installierte APT-Paket angefasst. Docker-, manuelle und andere Nicht-APT-Installationen werden nicht verändert. Keine echte Paketaktualisierung auf einem Zielgerät wurde für diesen Integrationsbranch ausgeführt. |
| [#44 – sudo-Rechte begrenzen](https://github.com/diddip21/knx_to_openhab/pull/44) | Unsichtbare Sicherheitsänderung: Der Webdienst kann nicht mehr beliebige Git- oder Systembefehle als root ausführen. | Bei einer bestehenden Installation muss die sudoers-Migration durch einen Administrator abgeschlossen sein. Der Setup-Schritt ersetzt die alte breite Regel und validiert die neue Policy. |
| [#45 – OpenHAB-Deployment begrenzen](https://github.com/diddip21/knx_to_openhab/pull/45) | Generierte Dateien werden auf festgelegte, konfigurierte OpenHAB-Ausgaben begrenzt. Manuell gepflegte Dateien werden beim Deploy und Rollback nicht überschrieben. | Konfigurierte Ausgabepfade müssen unter dem vorgesehenen OpenHAB-Konfigurationsverzeichnis und in den erwarteten Ausgabeordnern liegen. Bei Änderung der Ziele den Setup-/Rechte-Provisionierungsschritt erneut ausführen. |
| [#46 – Runtime-Pfade vereinheitlichen](https://github.com/diddip21/knx_to_openhab/pull/46) | Konfiguration, Generatorregeln, Jobs, Uploads und Sicherungen liegen an dauerhaften, getrennten Orten. Bestehende Daten werden beim Setup migriert. | Auf installierten Systemen übernimmt der Setup-Lauf die Migration. Standardorte: `/etc/knx_to_openhab` für Systemkonfiguration, `/var/lib/knx_to_openhab` für veränderliche Daten und `/var/backups/knx_to_openhab` für Sicherungen. Migration ist wiederholbar; bei Konflikten bitte Fehlermeldung beheben und erneut ausführen, nicht Quelldateien manuell löschen. |
| [#47 – Standardpasswort entfernen](https://github.com/diddip21/knx_to_openhab/pull/47) | Neuinstallationen verwenden ein individuelles Passwort; gespeicherte Web-UI-Zugangsdaten liegen als Argon2id-Hash außerhalb des Repositorys. | Bei einer Neuinstallation mindestens 12 Zeichen setzen und bestätigen. Bestehende Passwörter werden bei Setup migriert, ohne sie auszusperren. Das Passwort später mit `installer/set_ui_password.py` ändern. |
| [#48 – Sitzungen, CSRF und sichere Listener-Defaults](https://github.com/diddip21/knx_to_openhab/pull/48) | Anmeldung, Logout, geschützte Browser-Sitzungen, Ablauf und Abwehr schreibender Fremdanfragen. Standardmäßig lauscht die Oberfläche nur lokal. | Für lokalen Rechnerzugriff `http://127.0.0.1:8085`. Für Fernzugriff SSH-Tunnel verwenden (siehe unten) oder einen abgesicherten HTTPS-Reverse-Proxy konfigurieren. Die Oberfläche zählt nach fünf fehlgeschlagenen Anmeldungen innerhalb des 15-Minuten-Fensters eine Sperre für 15 Minuten. |

## Bestehende Installation aktualisieren

1. Vor dem Upgrade eine aktuelle Sicherung von Konfiguration und OpenHAB-Dateien anlegen.
2. Den Integrationsbranch zunächst auf einem Testsystem oder einer separaten Installation prüfen. Dieser Branch ist noch kein Release.
3. Änderungen durch den Administrator mit dem Installer-/Setup-Ablauf einrichten. Das Setup migriert bestehende Pfade und Secrets und installiert die benötigten eingeschränkten Systemhelfer.
4. Prüfen, dass `/etc/knx_to_openhab/config.json`, `/etc/knx_to_openhab/secrets.env`, `/var/lib/knx_to_openhab` und `/var/backups/knx_to_openhab` erwartungsgemäß vorhanden sind.
5. Über SSH lokal auf die Weboberfläche zugreifen:

   ```bash
   ssh -L 8085:127.0.0.1:8085 <benutzer>@<geraete-ip>
   ```

   Danach im Browser `http://127.0.0.1:8085` öffnen.

6. Eigenes Web-UI-Passwort verwenden und in den Einstellungen Ausgabeformat, Gateway-IP und OpenHAB-Zielpfade prüfen.
7. Vor einem echten Deploy zunächst Job-Vorschau, Dateiliste und Differenzen prüfen. Bei Unsicherheit nicht deployen; Deployments haben eine Sicherung und Rollback für die verwalteten Dateien.

## Dokumentation für Betrieb und Entwicklung

- [Benutzerhandbuch](USER_GUIDE.md): Einstellungen, Login, YAML-Ausgabe, Gateway-IP und Zugriff.
- [Produktionsleitfaden](PRODUCTION_GUIDE.md): Installation, Datenmigration, Secrets, Netzwerkzugriff, Dateirechte und Backup.
- [Entwicklerleitfaden](DEVELOPER_GUIDE.md): Architektur, lokale Pfade, Tests und Änderungen.
- [Web-UI-Entwicklerhinweise](../web_ui/README.md): API, Runtime-Konfiguration, UI und Browser-Tests.
- [Upload-Sicherheit](SECURITY_UPLOAD.md): unterstützte Uploads, Limits und Schutzmechanismen.
- [Integrations-Testbericht](FEATURE_UPGRADE_TESTS.md): Branch-Prüfung, Konfliktlösungen und Testergebnisse.

## Noch offene Betriebsnachweise

Die CI prüft Unit-/Integrationstests, statische Prüfungen und Browserabläufe. Vor einer späteren Freigabe auf `main` sind zusätzlich die in der PR-Dokumentation benannten realen Systemprüfungen erforderlich: YAML-Smoke-Test auf openHAB 5.2, Paketupdate auf einem geeigneten Testgerät und Upgrade-/Datenmigration auf einer repräsentativen Bestandsinstallation.
