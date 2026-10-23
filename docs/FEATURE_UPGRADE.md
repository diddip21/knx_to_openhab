# Feature Upgrade – integrierter Stand der offenen PRs

**Branch:** `developer/feature-upgrade`  
**Dokumentationsstand:** 23.10.2026  
**Ausgangsbasis:** `main` (`f092abd`)  
**Umfang:** Die elf am 23.10.2026 offenen PRs #33, #35, #37, #39, #42–#48 sind auf diesem Integrationsbranch zusammengeführt. `main` ist davon nicht verändert. PR #39 war zum Prüfzeitpunkt ein Draft. Die Aufnahme hier ist eine Integrationsprüfung und kein Release auf `main`.

> [!CAUTION]
> **Nicht auf einer bestehenden produktiven Installation installieren oder `setup.sh` ausführen.** Dieser Branch enthält noch nicht auf einer repräsentativen Bestandsanlage geprüfte Änderungen an Installation, Laufzeitdaten und Systemdiensten. Die Tests auf GitHub belegen die Softwaretests, aber keine sichere Migration oder Wiederherstellung eines realen Geräts. Diese Arbeit hat keine vorhandene Anlage verändert.

Für Anwender reicht diese Seite: Sie zeigt die sichtbaren Änderungen und ihre Bedienung. Technische Prüf- und Installationsdetails stehen in den Admin-/Entwicklerdokumenten am Seitenende.

## Kurz für Anwender

- **Jetzt ist nichts zu tun:** Der Branch ist noch nicht freigegeben. Bestehende Installationen und `main` wurden nicht verändert.
- **Die bisherige Ausgabe bleibt Standard:** Wer kein neues Format auswählt, arbeitet weiter mit den bisherigen `.things`, `.items` und `.sitemap`-Dateien.
- **Neue Funktionen sind optional:** YAML-Ausgabe, feste Gateway-IP und Paketupdates werden nur genutzt, wenn man sie in der Oberfläche auswählt.
- **YAML erzeugt keine parallelen Modell-Dateien:** Bei bewusst gewähltem YAML ersetzt `yaml/knx.yaml` die drei generierten Modell-Dateien. `influxdb.persist` und `fenster.rules` bleiben wie bisher Textdateien.
- **Die vielen neuen Repository-Dateien sind überwiegend Programmcode, Tests und Screenshots:** Sie erzeugen keine zusätzlichen openHAB-Konfigurationsdateien, die Anwender einzeln verwalten müssten.
- **Die geplante Migration legt Systemdaten an getrennten Orten ab:** `/etc/knx_to_openhab`, `/var/lib/knx_to_openhab` und `/var/backups/knx_to_openhab`. Das soll der Installer automatisch verwalten. Auf bestehenden Anlagen ist dieser Schritt noch nicht erprobt und deshalb vorerst gesperrt.

## Vorher und nachher

### Weboberfläche und Anmeldung

**Vorher:** Auf `main` öffnete sich die KNX-Weboberfläche direkt mit dem Dashboard. Es gab keinen Anmeldebildschirm.

![Vorher: Dashboard ohne vorgeschaltete Anmeldung](screenshots/feature-upgrade/before-main-dashboard.png)

**Nachher:** Die Weboberfläche verlangt eine Anmeldung. Nach erfolgreicher Anmeldung erscheint das Dashboard. Nach Ablauf der Sitzung leitet die Oberfläche zurück zur Anmeldung.

![Nachher: Anmeldeseite](screenshots/feature-upgrade/after-login.png)

![Nachher: angemeldetes Dashboard](screenshots/feature-upgrade/after-authenticated-dashboard.png)

![Nachher: erneute Anmeldung nach Sitzungsablauf](screenshots/feature-upgrade/after-session-expiry.png)

Die eingecheckten Nachher-Aufnahmen stammen aus automatisierten Playwright-Läufen. Der integrierte Softwarestand (Commit `3340ad2`) wurde zusätzlich in [GitHub Actions Run #516](https://github.com/diddip21/knx_to_openhab/actions/runs/40021087430) geprüft: 108 UI-Tests bestanden, 2 übersprungen. Der Lauf hat ein [Screenshot-Artefakt](https://github.com/diddip21/knx_to_openhab/actions/runs/40021087430/artifacts/12529744512) mit drei Dateien erzeugt (abrufbar bis 21.01.2027). Die Bilder zeigen synthetische Testdaten. Es wurde kein Video erzeugt; Playwright behält Videos nur bei fehlgeschlagenen Tests.

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
| [#44 – sudo-Rechte begrenzen](https://github.com/diddip21/knx_to_openhab/pull/44) | Unsichtbare Sicherheitsänderung: Der Webdienst kann nicht mehr beliebige Git- oder Systembefehle als root ausführen. | Die Änderung ersetzt die bestehende sudoers-Regel. Das ist ein Eingriff in die Systemberechtigungen und darf auf diesem Integrationsbranch nicht an einer produktiven Anlage ausgeführt werden. |
| [#45 – OpenHAB-Deployment begrenzen](https://github.com/diddip21/knx_to_openhab/pull/45) | Generierte Dateien werden auf festgelegte, konfigurierte OpenHAB-Ausgaben begrenzt. Manuell gepflegte Dateien werden beim Deploy und Rollback nicht überschrieben. | Konfigurierte Ausgabepfade müssen unter dem vorgesehenen OpenHAB-Konfigurationsverzeichnis und in den erwarteten Ausgabeordnern liegen. Bei Änderung der Ziele den Setup-/Rechte-Provisionierungsschritt erneut ausführen. |
| [#46 – Runtime-Pfade vereinheitlichen](https://github.com/diddip21/knx_to_openhab/pull/46) | Konfiguration, Generatorregeln, Jobs, Uploads und Sicherungen sollen an dauerhaften, getrennten Orten liegen. | Der Installer enthält eine Migration in `/etc/knx_to_openhab`, `/var/lib/knx_to_openhab` und `/var/backups/knx_to_openhab`. Sie wurde nur automatisiert getestet. Sie kopiert Daten, veröffentlicht neue Pfade und löscht anschließend alte Jobs-/Backup-Ordner im Installationsbaum. Bis eine Bestandsmigration mit Wiederherstellung erprobt ist, nicht auf produktiven Geräten ausführen. |
| [#47 – Standardpasswort entfernen](https://github.com/diddip21/knx_to_openhab/pull/47) | Neuinstallationen verwenden ein individuelles Passwort; gespeicherte Web-UI-Zugangsdaten liegen als Argon2id-Hash außerhalb des Repositorys. | Beim Setup wird die Anmeldung migriert bzw. bei einem ausgelieferten Standardpasswort ein neues Passwort verlangt. Das ändert die Zugangsdatenablage und kann eine manuelle Eingabe verlangen. Verhalten und Rückweg wurden nicht auf einer Bestandsanlage abgenommen. |
| [#48 – Sitzungen, CSRF und sichere Listener-Defaults](https://github.com/diddip21/knx_to_openhab/pull/48) | Anmeldung, Logout, geschützte Browser-Sitzungen, Ablauf und Abwehr schreibender Fremdanfragen. Standardmäßig lauscht die Oberfläche nur lokal. | Setup fragt bei einer bisherigen LAN-Bind-Adresse nach. Ohne bestätigtes `y` (auch ohne interaktives Terminal) wird auf `127.0.0.1` umgestellt; ein bisheriger Fernzugriff kann dadurch abbrechen. Für neue Installationen SSH-Tunnel verwenden oder einen abgesicherten HTTPS-Reverse-Proxy konfigurieren. |

## Status für bestehende Installationen

**Es gibt für diesen Branch derzeit keine freigegebene Upgrade-Anleitung.** Die vorige Anleitung hat zu früh zum Ausführen des Setup-Skripts auf installierten Systemen aufgefordert; das war missverständlich und ist korrigiert.

Ein Setup auf einem vorhandenen Gerät würde unter anderem:

- `knxohui.service` sowie den Backup-Aufräumdienst stoppen und später den Webdienst mit neuen systemd-Dateien neu starten;
- Konfiguration, Jobs, Upload-/Staging-Daten und Sicherungen in externe Verzeichnisse migrieren, Pfade umschalten und die alten Jobs-/Backup-Verzeichnisse im Installationsbaum löschen;
- Generator-Konfiguration im Installationsverzeichnis durch die Vorlagenversion ersetzen, nachdem die Runtime-Konfiguration ausgelagert wurde;
- Web-UI-Zugangsdaten in eine externe Secret-Datei überführen und gegebenenfalls ein neues Passwort verlangen;
- bei fehlender ausdrücklicher Terminalbestätigung eine bisherige LAN-Bind-Adresse auf `127.0.0.1` ändern, wodurch Fernzugriff ausfallen kann;
- Dateieigentümer, OpenHAB-Ausgaberechte und die sudoers-Policy auf dem Host ändern.

Das sind absichtliche Upgrade-Änderungen des integrierten Codes, aber keine folgenlose Installation. Ein Backup allein belegt keinen sicheren Rollback. Vor einer Freigabe fehlen eine Probe mit einer Kopie repräsentativer Bestandsdaten, ein geprüfter Wiederherstellungslauf, eine klare Vorab-Anzeige der Änderungen sowie ein dokumentierter Abbruch-/Rollback-Pfad. Bis diese Nachweise vorliegen, den Branch nur zur Prüfung verwenden und nicht auf produktiven Bestandsgeräten installieren oder dessen Setup-/Migrationsskripte ausführen.

Die bisherigen Anlagen wurden im Rahmen dieser Integration nicht angesprochen oder verändert. `main` ist unverändert; der Branch selbst ändert keine Installation, solange sein Code nicht auf einem Gerät ausgeführt wird.

## Dokumentation für Betrieb und Entwicklung

- [Benutzerhandbuch](USER_GUIDE.md): Einstellungen, Login, YAML-Ausgabe, Gateway-IP und Zugriff.
- [Produktionsleitfaden](PRODUCTION_GUIDE.md): Installation, Datenmigration, Secrets, Netzwerkzugriff, Dateirechte und Backup.
- [Entwicklerleitfaden](DEVELOPER_GUIDE.md): Architektur, lokale Pfade, Tests und Änderungen.
- [Web-UI-Entwicklerhinweise](../web_ui/README.md): API, Runtime-Konfiguration, UI und Browser-Tests.
- [Upload-Sicherheit](SECURITY_UPLOAD.md): unterstützte Uploads, Limits und Schutzmechanismen.
- [Integrations-Testbericht](FEATURE_UPGRADE_TESTS.md): Branch-Prüfung, Konfliktlösungen und Testergebnisse.

## Noch offene Betriebsnachweise

Die CI prüft Unit-/Integrationstests, statische Prüfungen und Browserabläufe. Vor einer späteren Freigabe auf `main` sind zusätzlich die in der PR-Dokumentation benannten realen Systemprüfungen erforderlich: YAML-Smoke-Test auf openHAB 5.2, Paketupdate auf einem geeigneten Testgerät und Upgrade-/Datenmigration auf einer repräsentativen Bestandsinstallation.
