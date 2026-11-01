(() => {
  const STORAGE_KEY = 'knx_to_openhab.locale'
  const catalogs = {
    de: {
      'language.label': 'Sprache / Language',
      'language.de': 'Deutsch',
      'language.en': 'English',
      'app.title': 'KNX → OpenHAB Generator',
      'login.title': 'Anmelden · KNX zu OpenHAB'
    },
    en: {
      'language.label': 'Sprache / Language',
      'language.de': 'Deutsch',
      'language.en': 'English',
      'app.title': 'KNX → OpenHAB Generator',
      'login.title': 'Sign in · KNX to OpenHAB'
    }
  }
  Object.assign(catalogs.de, {
    'header.logoAlt': 'Logo',
    'header.checkUpdates': 'Klicken, um nach Updates zu suchen',
    'header.version': 'Version:',
    'header.loading': 'Wird geladen …',
    'header.unknown': 'Unbekannt',
    'header.logout': 'Abmelden',
    'upload.heading': 'KNX-Projekt hochladen',
    'upload.fileLabel': 'KNX-Projektdatei:',
    'upload.passwordLabel': 'Passwort (falls geschützt):',
    'upload.optional': 'Optional',
    'upload.preview': 'Strukturvorschau',
    'upload.submit': 'Hochladen & Verarbeiten',
    'preview.buildingHeading': 'Gebäudestruktur-Vorschau',
    'jobs.heading': 'Aufträge',
    'jobDetails.heading': 'Auftragsdetails',
    'logs.heading': 'Live-Protokoll',
    'logs.filter': 'Protokollfilter:',
    'logs.all': 'Alle',
    'logs.debug': 'Debug',
    'logs.info': 'Info',
    'logs.warning': 'Warnung',
    'logs.error': 'Fehler',
    'stats.heading': 'Statistik der erzeugten Dateien',
    'stats.expertTitle': 'Vollständigkeitsübersicht anzeigen',
    'stats.expert': 'Expertenmodus',
    'stats.expertHelp': 'Vollständigkeitsübersicht',
    'stats.tipBefore': 'Hinweis: Berichte wie ',
    'stats.tipMiddle': ' und ',
    'stats.tipAfter': ' können in der Tabelle angezeigt, heruntergeladen oder kopiert werden.',
    'settings.heading': 'Konfigurationseinstellungen',
    'settings.general': 'Allgemein',
    'settings.devices': 'Geräte',
    'settings.mappings': 'Zuordnungen',
    'settings.definitions': 'Definitionen',
    'settings.advanced': 'Erweitert',
    'settings.modelFormat': 'OpenHAB-Modellformat',
    'settings.legacyFormat': 'Legacy DSL (.things/.items/.sitemap)',
    'settings.yamlFormat': 'openHAB 5.2 YAML',
    'settings.yamlHelp': 'YAML fasst Things, Items und Sitemap in einer versionierten Datei zusammen. Persistence und die zustandsbehaftete Fensterregel bleiben Textdateien.',
    'settings.yamlPath': 'YAML-Pfad',
    'settings.itemsPath': 'Items-Pfad',
    'settings.thingsPath': 'Things-Pfad',
    'settings.sitemapsPath': 'Sitemaps-Pfad',
    'settings.influxPath': 'InfluxDB-Pfad',
    'settings.windowRulesPath': 'Pfad der Fensterregeln',
    'settings.naming': 'Benennung & Heuristiken',
    'settings.floorAsIs': 'Etagenname unverändert übernehmen',
    'settings.floorAsIsHelp': 'Den Etagennamen genau wie in ETS definiert verwenden.',
    'settings.floorDescription': 'Etagenname aus Beschreibung übernehmen',
    'settings.floorDescriptionHelp': 'Das ETS-Beschreibungsfeld als Etagenname verwenden.',
    'settings.roomAsIs': 'Raumname unverändert übernehmen',
    'settings.roomAsIsHelp': 'Den Raumnamen genau wie in ETS definiert verwenden.',
    'settings.roomDescription': 'Raumname aus Beschreibung übernehmen',
    'settings.roomDescriptionHelp': 'Das ETS-Beschreibungsfeld als Raumnamen verwenden.',
    'settings.addMissingItems': 'Fehlende Items ergänzen',
    'settings.addMissingItemsHelp': 'OpenHAB-Items für Gruppenadressen ohne explizite Zuordnung erstellen.',
    'settings.autoPlace': 'Unbekannte Adressen automatisch zuordnen',
    'settings.autoPlaceHelp': 'Fehlende Etagen/Räume für unbekannte Adressen anlegen, um „Unknown“-Berichte zu reduzieren.',
    'settings.namingInfo': 'Benennungsheuristiken steuern, wie Etagen und Räume aus ETS abgeleitet werden. Kombinieren Sie die Optionen passend zur Projektstruktur.',
    'settings.unknownFloor': 'Unbekannter Etagenname',
    'settings.unknownRoom': 'Unbekannter Raumname',
    'settings.centralFunctionKeyword': 'Suchbegriff für zentrale Funktionen',
    'settings.centralFunctionGroup': 'Gruppe für zentrale Funktionen',
    'settings.centralSensorKeyword': 'Suchbegriff für zentrale Meldungen/Sensoren',
    'settings.gateway': 'Gateway',
    'settings.gatewayHardwareNames': 'Hardware-Namen (durch Komma getrennt)',
    'settings.gatewayNamesHelp': 'Namen zur Erkennung der KNX-IP-Schnittstelle/des Routers',
    'settings.gatewayIp': 'KNX-Gateway-IP überschreiben',
    'settings.gatewayIpPlaceholder': 'Automatisch im ETS-Projekt erkennen',
    'settings.gatewayIpHelp': 'IPv4- oder IPv6-Adresse eingeben, um den ETS-Wert zu überschreiben. Für automatische Erkennung bei einer späteren Generierung leer lassen.',
    'settings.gatewayMigrationTitle': 'Vorschau der Ausgabeformat-Migration',
    'settings.gatewayMigrationOld': 'Bisherige Generatorausgabe: ',
    'settings.gatewayMigrationNew': 'Neue Generatorausgabe: ',
    'settings.gatewayMigrationOwn': 'Nur vom Generator verwaltete Ziele werden migriert; manuelle Dateien bleiben unverändert.',
    'settings.gatewayLiveHelp': 'Live-Aktionen ändern nur die verwaltete Modelldatei der letzten erfolgreichen Bereitstellung und die gespeicherte Gateway-Überschreibung. Änderungen an Format oder Pfad werden erst bei der Bereitstellung wirksam. OpenHAB wird nicht neu gestartet; der Laufzeitstatus wird nicht geprüft.',
    'settings.gatewayApplyLive': 'IP in die aktive OpenHAB-Datei übernehmen',
    'settings.gatewayRestoreEts': 'ETS-Adresse wiederherstellen',
    'settings.gatewayUndo': 'Letzte Live-Änderung rückgängig machen',
    'gateway.loadingState': 'Verwalteter Gateway-Dateistatus wird geladen …',
    'gateway.state': 'Verwaltete {format}-Datei {path}: {mode} unter {address}. ETS-Quelle: {detected}. Laufzeitstatus nicht geprüft.',
    'gateway.stateUnavailable': 'Status der verwalteten Gateway-Datei nicht verfügbar: {error}',
    'gateway.state.unknownPath': 'unbekannter bereitgestellter Pfad',
    'gateway.state.unknownMode': 'unbekannter Modus',
    'gateway.state.notConfigured': 'nicht konfiguriert',
    'gateway.state.noEtsIp': 'keine ETS-IP erkannt',
    'gateway.error.noTarget': 'Kein nutzbares bereitgestelltes KNX-Things-Ziel vorhanden',
    'gateway.error.invalidIp': 'Ungültige IP-Adresse: {address}',
    'gateway.error.ipRequired': 'Eine nicht leere IP-Adresse ist erforderlich',
    'gateway.error.overrideType': 'Die Gateway-IP-Überschreibung muss eine Zeichenfolge sein',
    'gateway.error.applyFailed': 'Gateway-IP konnte nicht aktualisiert werden',
    'gateway.error.resetFailed': 'ETS-Gateway-Adresse konnte nicht wiederhergestellt werden',
    'gateway.error.undoFailed': 'Letzte Gateway-Änderung konnte nicht rückgängig gemacht werden',
    'gateway.format.unsupported': 'YAML erfordert OpenHAB 5.2 oder neuer. Installierte Version: {version}. YAML-Generierung und Bereitstellung sind gesperrt.',
    'gateway.format.unknown': 'OpenHAB-Version konnte nicht ermittelt werden; die YAML-Kompatibilität kann nicht bestätigt werden.',
    'gateway.format.requires52': '✗ YAML erfordert OpenHAB 5.2 oder neuer.',
    'gateway.live.noTarget': 'Live-Gateway-Aktionen sind nicht verfügbar, da kein nutzbares, erfolgreich bereitgestelltes KNX-Things-Ziel vorhanden ist.',
    'gateway.live.yamlUnsupported': 'Live-Gateway-Aktionen sind deaktiviert, da das bereitgestellte YAML-Modell eine bekannte OpenHAB-Installation ab Version 5.2 erfordert. Installierte Version: {version}.',
    'gateway.live.yamlUnknown': 'Live-Gateway-Aktionen sind deaktiviert, da das bereitgestellte YAML-Modell eine bekannte OpenHAB-Installation ab Version 5.2 erfordert. Die installierte Version konnte nicht ermittelt werden.',
    'gateway.apply.emptyIp': 'Geben Sie eine nicht leere IPv4- oder IPv6-Adresse ein.',
    'gateway.apply.confirm': 'Diese IP-Adresse auf die verwaltete OpenHAB-Datei anwenden? Die KNX-Verbindung kann kurzzeitig unterbrochen werden.',
    'gateway.restore.confirm': 'Die Gateway-Adresse aus dem zuletzt erfolgreich bereitgestellten ETS-Projekt wiederherstellen? Die KNX-Verbindung kann kurzzeitig unterbrochen werden.',
    'gateway.undo.confirm': 'Die letzte Live-Änderung an der bereitgestellten KNX-Things-Datei und der gespeicherten Gateway-Überschreibung rückgängig machen? Der OpenHAB-Laufzeitstatus wird nicht geprüft.',
    'gateway.apply.updating': 'Verwaltete KNX-Gateway-Datei wird aktualisiert …',
    'gateway.restore.restoring': 'Bereitgestellte ETS-Gateway-Einstellung wird wiederhergestellt …',
    'gateway.undo.undoing': 'Letzte Live-Gateway-Dateiänderung wird rückgängig gemacht …',
    'gateway.action.updated': '✓ Datei aktualisiert; OpenHAB-Laufzeitstatus nicht geprüft',
    'gateway.action.restored': '✓ Datei wiederhergestellt; OpenHAB-Laufzeitstatus nicht geprüft',
    'gateway.action.error': '✗ {error}',
    'gateway.migration.confirm': 'Das generierte OpenHAB-Modell von {oldPath} nach {newPath} migrieren? Verwaltete alte Ausgaben werden gesichert und entfernt; manuelle Dateien bleiben unverändert.',
    'settings.searchMappings': 'Zuordnungen suchen …',
    'settings.dpst': 'DPST',
    'settings.gaPrefix': 'GA-Präfix',
    'settings.itemType': 'Item-Typ',
    'settings.semanticInfo': 'Semantische Information',
    'settings.actions': 'Aktionen',
    'settings.regexPatterns': 'Regex-Muster',
    'settings.reload': 'Konfiguration neu laden',
    'settings.saveAndReprocess': 'Speichern & letzten Auftrag erneut verarbeiten',
    'settings.save': 'Konfiguration speichern',
    'services.heading': 'Dienste',
    'services.note': 'APT-Pakete auf diesem Gerät. Die verfügbare Version stammt aus den Paketlisten.',
    'services.refresh': 'Paketlisten prüfen',
    'footer.readme': 'README',
    'updates.available': 'Systemupdate verfügbar',
    'updates.currentVersion': 'Aktuelle Version',
    'updates.newVersion': 'Neue Version',
    'updates.commit': 'Commit:',
    'updates.message': 'Nachricht:',
    'updates.date': 'Datum:',
    'updates.author': 'Autor:',
    'common.cancel': 'Abbrechen',
    'updates.install': 'Update installieren',
    'updates.log': 'Update-Protokoll',
    'updates.waitingLogs': 'Warte auf Protokolle …',
    'common.close': 'Schließen',
    'updates.initiated': 'Update gestartet!',
    'updates.restarting': 'Das System wird neu gestartet, um die Änderungen anzuwenden.',
    'updates.secondsUntilReload': 'Sekunden bis zum Neuladen',
    'rollback.title': 'Aus Backup wiederherstellen',
    'rollback.select': 'Backup zum Wiederherstellen auswählen:',
    'rollback.action': 'Wiederherstellen',
    'summary.title': 'Vollständigkeitsübersicht',
    'filePreview.finalView': 'Endansicht',
    'filePreview.diffView': 'Änderungsansicht',
    'filePreview.added': 'Hinzugefügt',
    'filePreview.deleted': 'Gelöscht',
    'filePreview.modified': 'Geändert',
    'filePreview.noDiffs': 'Keine Unterschiede vorhanden.',
    'filePreview.emptyDiff': '(leerer Diff)',
    'filePreview.emptyFile': '(leere Datei)',
    'login.heading': 'Anmelden',
    'login.intro': 'Geben Sie Ihre Web-UI-Zugangsdaten ein, um fortzufahren.',
    'login.username': 'Benutzername',
    'login.password': 'Passwort',
    'login.submit': 'Anmelden',
    'common.closeDialog': 'Dialog schließen'
  })
  Object.assign(catalogs.en, {
    'header.logoAlt': 'Logo',
    'header.checkUpdates': 'Click to check for updates',
    'header.version': 'Version:',
    'header.loading': 'Loading …',
    'header.unknown': 'Unknown',
    'header.logout': 'Log out',
    'upload.heading': 'Upload KNX Project',
    'upload.fileLabel': 'KNX Project File:',
    'upload.passwordLabel': 'Password (if protected):',
    'upload.optional': 'Optional',
    'upload.preview': 'Preview Structure',
    'upload.submit': 'Upload & Process',
    'preview.buildingHeading': 'Building Structure Preview',
    'jobs.heading': 'Jobs',
    'jobDetails.heading': 'Job Details',
    'logs.heading': 'Live Log',
    'logs.filter': 'Log Level Filter:',
    'logs.all': 'All',
    'logs.debug': 'Debug',
    'logs.info': 'Info',
    'logs.warning': 'Warning',
    'logs.error': 'Error',
    'stats.heading': 'Generated Files Statistics',
    'stats.expertTitle': 'Show completeness summary',
    'stats.expert': 'Expert',
    'stats.expertHelp': 'Completeness summary',
    'stats.tipBefore': 'Tip: Reports like ',
    'stats.tipMiddle': ' and ',
    'stats.tipAfter': ' can be previewed, downloaded, or copied from the table.',
    'settings.heading': 'Configuration Settings',
    'settings.general': 'General',
    'settings.devices': 'Devices',
    'settings.mappings': 'Mappings',
    'settings.definitions': 'Definitions',
    'settings.advanced': 'Advanced',
    'settings.modelFormat': 'OpenHAB Model Format',
    'settings.legacyFormat': 'Legacy DSL (.things/.items/.sitemap)',
    'settings.yamlFormat': 'openHAB 5.2 YAML',
    'settings.yamlHelp': 'YAML combines Things, Items and the Sitemap in one versioned file. Persistence and the stateful window rule remain textual.',
    'settings.yamlPath': 'YAML Path',
    'settings.itemsPath': 'Items Path',
    'settings.thingsPath': 'Things Path',
    'settings.sitemapsPath': 'Sitemaps Path',
    'settings.influxPath': 'InfluxDB Path',
    'settings.windowRulesPath': 'Window Rules Path',
    'settings.naming': 'Naming & Heuristics',
    'settings.floorAsIs': 'Floor Name As Is',
    'settings.floorAsIsHelp': 'Use the floor name exactly as defined in ETS.',
    'settings.floorDescription': 'Floor Name From Description',
    'settings.floorDescriptionHelp': 'Use the ETS description field as the floor name.',
    'settings.roomAsIs': 'Room Name As Is',
    'settings.roomAsIsHelp': 'Use the room name exactly as defined in ETS.',
    'settings.roomDescription': 'Room Name From Description',
    'settings.roomDescriptionHelp': 'Use the ETS description field as the room name.',
    'settings.addMissingItems': 'Add Missing Items',
    'settings.addMissingItemsHelp': 'Create OpenHAB items for group addresses without an explicit mapping.',
    'settings.autoPlace': 'Auto-place unknown addresses',
    'settings.autoPlaceHelp': 'Create missing floors/rooms for unknown addresses to reduce “Unknown” reports.',
    'settings.namingInfo': 'Naming heuristics control how floors and rooms are inferred from ETS. Combine options as needed for your project structure.',
    'settings.unknownFloor': 'Unknown Floor Name',
    'settings.unknownRoom': 'Unknown Room Name',
    'settings.centralFunctionKeyword': 'Central Function Keyword',
    'settings.centralFunctionGroup': 'Central Function Group',
    'settings.centralSensorKeyword': 'Central Notification/Sensor Keyword',
    'settings.gateway': 'Gateway',
    'settings.gatewayHardwareNames': 'Hardware Names (comma separated)',
    'settings.gatewayNamesHelp': 'Names to identify the KNX IP Interface/Router',
    'settings.gatewayIp': 'KNX Gateway IP Override',
    'settings.gatewayIpPlaceholder': 'Auto-detect from ETS project',
    'settings.gatewayIpHelp': 'Enter an IPv4 or IPv6 address to override the ETS value. Leave blank for automatic detection during a future generation.',
    'settings.gatewayMigrationTitle': 'Output format migration preview',
    'settings.gatewayMigrationOld': 'Old generator output: ',
    'settings.gatewayMigrationNew': 'New generator output: ',
    'settings.gatewayMigrationOwn': 'Only generator-owned targets are migrated; manual files remain untouched.',
    'settings.gatewayLiveHelp': 'Live actions change only the managed model file from the last successful deployment and the saved gateway override. Pending format or path changes take effect after deployment. OpenHAB is not restarted, and runtime status is not checked.',
    'settings.gatewayApplyLive': 'Apply IP to live OpenHAB file',
    'settings.gatewayRestoreEts': 'Restore ETS address',
    'settings.gatewayUndo': 'Undo last live change',
    'gateway.loadingState': 'Loading managed gateway file state…',
    'gateway.state': 'Managed {format} file {path}: {mode} at {address}. ETS source: {detected}. Runtime status not checked.',
    'gateway.stateUnavailable': 'Managed gateway file state unavailable: {error}',
    'gateway.state.unknownPath': 'unknown deployed path',
    'gateway.state.unknownMode': 'unknown mode',
    'gateway.state.notConfigured': 'not configured',
    'gateway.state.noEtsIp': 'no ETS IP detected',
    'gateway.error.noTarget': 'No usable deployed KNX Things target',
    'gateway.error.invalidIp': 'Invalid IP address: {address}',
    'gateway.error.ipRequired': 'A non-empty IP address is required',
    'gateway.error.overrideType': 'Generator gateway IP override must be a string',
    'gateway.error.applyFailed': 'Gateway IP update failed',
    'gateway.error.resetFailed': 'Could not restore the ETS gateway address',
    'gateway.error.undoFailed': 'Could not undo the last gateway change',
    'gateway.format.unsupported': 'YAML requires OpenHAB 5.2 or newer. Installed version: {version}. YAML generation and deployment are blocked.',
    'gateway.format.unknown': 'OpenHAB version could not be determined; YAML compatibility cannot be confirmed.',
    'gateway.format.requires52': '✗ YAML requires OpenHAB 5.2 or newer.',
    'gateway.live.noTarget': 'Live gateway actions are unavailable because no usable successfully deployed KNX Things target is available.',
    'gateway.live.yamlUnsupported': 'Live gateway actions are disabled because the deployed YAML model requires a known OpenHAB 5.2 or newer installation. Installed version: {version}.',
    'gateway.live.yamlUnknown': 'Live gateway actions are disabled because the deployed YAML model requires a known OpenHAB 5.2 or newer installation. Installed version could not be determined.',
    'gateway.apply.emptyIp': 'Enter a non-empty IPv4 or IPv6 address.',
    'gateway.apply.confirm': 'Apply this IP to the managed OpenHAB file? The KNX link may briefly reconnect.',
    'gateway.restore.confirm': 'Restore the gateway address from the last successfully deployed ETS project? The KNX link may briefly reconnect.',
    'gateway.undo.confirm': 'Undo the last live change to the deployed KNX Things file and saved gateway override? OpenHAB runtime status will not be checked.',
    'gateway.apply.updating': 'Updating the managed KNX gateway file…',
    'gateway.restore.restoring': 'Restoring the deployed ETS gateway setting…',
    'gateway.undo.undoing': 'Undoing the last live gateway file change…',
    'gateway.action.updated': '✓ File updated; OpenHAB runtime status not checked',
    'gateway.action.restored': '✓ File restored; OpenHAB runtime status not checked',
    'gateway.action.error': '✗ {error}',
    'gateway.migration.confirm': 'Migrate the generated OpenHAB model from {oldPath} to {newPath}? Managed old outputs are backed up and retired; manual files are not changed.',
    'settings.searchMappings': 'Search mappings...',
    'settings.dpst': 'DPST',
    'settings.gaPrefix': 'GA Prefix',
    'settings.itemType': 'Item Type',
    'settings.semanticInfo': 'Semantic Info',
    'settings.actions': 'Actions',
    'settings.regexPatterns': 'Regex Patterns',
    'settings.reload': 'Reload Config',
    'settings.saveAndReprocess': 'Save & Reprocess Last Job',
    'settings.save': 'Save Config',
    'services.heading': 'Services',
    'services.note': 'APT packages on this device. Available versions come from the package lists.',
    'services.refresh': 'Check package lists',
    'footer.readme': 'README',
    'updates.available': 'System Update Available',
    'updates.currentVersion': 'Current Version',
    'updates.newVersion': 'New Version',
    'updates.commit': 'Commit:',
    'updates.message': 'Message:',
    'updates.date': 'Date:',
    'updates.author': 'Author:',
    'common.cancel': 'Cancel',
    'updates.install': 'Install Update',
    'updates.log': 'Update Log',
    'updates.waitingLogs': 'Waiting for logs...',
    'common.close': 'Close',
    'updates.initiated': 'Update Initiated!',
    'updates.restarting': 'The system is restarting to apply changes.',
    'updates.secondsUntilReload': 'seconds until reload',
    'rollback.title': 'Rollback to Backup',
    'rollback.select': 'Select a backup to restore:',
    'rollback.action': 'Rollback',
    'summary.title': 'Completeness Summary',
    'filePreview.finalView': 'Final View',
    'filePreview.diffView': 'Diff View',
    'filePreview.added': 'Added',
    'filePreview.deleted': 'Deleted',
    'filePreview.modified': 'Modified',
    'filePreview.noDiffs': 'No differences available.',
    'filePreview.emptyDiff': '(empty diff)',
    'filePreview.emptyFile': '(empty file)',
    'login.heading': 'Sign in',
    'login.intro': 'Enter your Web UI credentials to continue.',
    'login.username': 'Username',
    'login.password': 'Password',
    'login.submit': 'Sign in',
    'common.closeDialog': 'Close dialog'
  })
  Object.assign(catalogs.de, {
    'job.status.queued': 'In Warteschlange',
    'job.status.running': 'Läuft',
    'job.status.completed': 'Abgeschlossen',
    'job.status.failed': 'Fehlgeschlagen',
    'job.status.pending': 'Ausstehend',
    'job.action.details': 'Details',
    'job.action.structure': 'Struktur',
    'job.action.diff': 'Änderungen',
    'job.action.deploy': 'Bereitstellen',
    'job.action.rollback': 'Wiederherstellen',
    'job.diffTitle': 'Diff für Auftrag {id}',
    'job.action.delete': 'Löschen',
    'job.detail.id': 'ID:',
    'job.detail.name': 'Name:',
    'job.detail.status': 'Status:',
    'job.detail.created': 'Erstellt:',
    'job.detail.backups': 'Backups:',
    'job.detail.latestBackup': 'Letztes Backup:',
    'job.loadingDetails': 'Auftragsdetails werden geladen …',
    'job.loadingLogs': 'Protokolle werden geladen …',
    'job.waitingEvents': 'Warte auf Ereignisse …',
    'job.noLogs': 'Keine Protokolle verfügbar',
    'job.failedLogs': 'Protokolle konnten nicht geladen werden',
    'job.errorLoadingDetails': 'Auftragsdetails konnten nicht geladen werden: {error}',
    'job.completed': 'Auftrag erfolgreich abgeschlossen.',
    'job.failed': 'Auftrag fehlgeschlagen{error}. Siehe Protokoll unten.',
    'upload.selectFile': 'Bitte wählen Sie zuerst eine Datei aus.',
    'upload.uploading': 'Datei wird hochgeladen …',
    'upload.started': 'Datei hochgeladen, Auftrag gestartet: {id}…',
    'upload.processing': 'Verarbeitung gestartet: {id}… Details finden Sie unten.',
    'upload.error': 'Upload-Fehler: {error}',
    'message.backupCreated': 'Sicherung erstellt: {filename}',
    'message.generationStarted': 'Generierung im Prozess gestartet',
    'message.backupFailed': 'Sicherung fehlgeschlagen: {error}',
    'message.retentionError': 'Fehler bei der Aufbewahrung: {error}',
    'message.stagingDirectory': 'Staging-Verzeichnis: {path}',
    'message.readJson': 'Projekt-JSON-Datei gelesen',
    'message.parsingKnxproj': 'KNX-Projektarchiv wird eingelesen (dies kann etwas dauern)',
    'message.parsedKnxproj': 'KNX-Projektarchiv eingelesen',
    'message.addressesExtracted': '{count} Gruppenadressen extrahiert',
    'message.previewSaveFailed': 'Projektstruktur-Vorschau konnte nicht gespeichert werden: {error}',
    'message.generatingStaged': 'Dateien werden in der Staging-Umgebung erzeugt …',
    'message.completenessWritten': 'Vollständigkeitsbericht geschrieben: {path}',
    'message.completenessFailed': 'Vollständigkeitsbericht fehlgeschlagen: {error}',
    'message.jobCompletedStaged': 'Abgeschlossen (zwischengespeichert) – bereit zur Bereitstellung',
    'message.running': 'Läuft',
    'message.completed': 'Abgeschlossen',
    'message.failed': 'Fehlgeschlagen',
    'message.jobFinished': 'Auftrag abgeschlossen',
    'message.statsError': 'Statistikfehler: {error}',
    'log.category.backup': 'Sicherung',
    'log.category.status': 'Status',
    'log.category.info': 'Info',
    'log.category.error': 'Fehler',
    'log.category.warning': 'Warnung',
    'log.category.debug': 'Debug',
    'log.category.stats': 'Statistik',
    'log.category.done': 'Fertig'
  })
  Object.assign(catalogs.en, {
    'job.status.queued': 'Queued',
    'job.status.running': 'Running',
    'job.status.completed': 'Completed',
    'job.status.failed': 'Failed',
    'job.status.pending': 'Pending',
    'job.action.details': 'Details',
    'job.action.structure': 'Structure',
    'job.action.diff': 'Diff',
    'job.action.deploy': 'Deploy',
    'job.action.rollback': 'Rollback',
    'job.diffTitle': 'Diff for job {id}',
    'job.action.delete': 'Delete',
    'job.detail.id': 'ID:',
    'job.detail.name': 'Name:',
    'job.detail.status': 'Status:',
    'job.detail.created': 'Created:',
    'job.detail.backups': 'Backups:',
    'job.detail.latestBackup': 'Latest Backup:',
    'job.loadingDetails': 'Loading job details…',
    'job.loadingLogs': 'Loading logs…',
    'job.waitingEvents': 'Waiting for events…',
    'job.noLogs': 'No logs available',
    'job.failedLogs': 'Failed to load logs',
    'job.errorLoadingDetails': 'Error loading job details: {error}',
    'job.completed': 'Job completed successfully.',
    'job.failed': 'Job failed{error}. Check logs below.',
    'upload.selectFile': 'Please select a file first.',
    'upload.uploading': 'Uploading file…',
    'upload.started': 'File uploaded, job started: {id}…',
    'upload.processing': 'Processing started: {id}… Check job details below.',
    'upload.error': 'Upload error: {error}',
    'message.backupCreated': 'Backup created: {filename}',
    'message.generationStarted': 'In-process generation started',
    'message.backupFailed': 'Backup failed: {error}',
    'message.retentionError': 'Retention error: {error}',
    'message.stagingDirectory': 'Staging directory: {path}',
    'message.readJson': 'Read project JSON dump',
    'message.parsingKnxproj': 'Parsing KNX project archive (this may take a while)',
    'message.parsedKnxproj': 'Parsed KNX project archive',
    'message.addressesExtracted': '{count} group addresses extracted',
    'message.previewSaveFailed': 'Project structure preview could not be saved: {error}',
    'message.generatingStaged': 'Generating files (staged)…',
    'message.completenessWritten': 'Completeness report written: {path}',
    'message.completenessFailed': 'Completeness report failed: {error}',
    'message.jobCompletedStaged': 'Completed (staged) - ready to deploy',
    'message.running': 'Running',
    'message.completed': 'Completed',
    'message.failed': 'Failed',
    'message.jobFinished': 'Job finished',
    'message.statsError': 'Stats error: {error}',
    'log.category.backup': 'Backup',
    'log.category.status': 'Status',
    'log.category.info': 'Info',
    'log.category.error': 'Error',
    'log.category.warning': 'Warning',
    'log.category.debug': 'Debug',
    'log.category.stats': 'Stats',
    'log.category.done': 'Done'
  })
  Object.assign(catalogs.de, {
    'common.delete': 'Löschen',
    'common.preview': 'Vorschau',
    'common.download': 'Herunterladen',
    'common.copy': 'Kopieren',
    'common.view': 'Anzeigen',
    'config.loading': 'Konfiguration wird geladen …',
    'config.loaded': '✓ Konfiguration geladen',
    'config.loadFailed': 'Konfiguration konnte nicht geladen werden',
    'config.loadError': '✗ Fehler: {error}',
    'config.saving': 'Konfiguration wird gespeichert …',
    'config.saved': '✓ Konfiguration gespeichert',
    'config.saveError': '✗ Fehler: {error}',
    'config.saveFailed': 'Konfiguration konnte nicht gespeichert werden',
    'config.noJob': 'Kein Auftrag zum erneuten Verarbeiten ausgewählt. Bitte wählen Sie zuerst einen Auftrag aus.',
    'config.reprocessing': 'Erneute Verarbeitung wird gestartet …',
    'config.reprocessStarted': '✓ Erneute Verarbeitung gestartet (Auftrag {id})',
    'config.reprocessFailed': '✗ Erneute Verarbeitung fehlgeschlagen: {error}',
    'preview.parseProject': 'Projektstruktur wird analysiert …',
    'preview.projectLoaded': '✓ Projektstruktur geladen',
    'preview.error': '✗ Fehler: {error}',
    'preview.project': 'Projekt:',
    'preview.gatewayIp': 'Gateway-IP:',
    'preview.totalAddresses': 'Gruppenadressen insgesamt:',
    'preview.enabled': 'Aktiviert',
    'preview.disabled': 'Deaktiviert',
    'preview.unknownItems': 'Unbekannte Elemente:',
    'preview.found': 'gefunden',
    'preview.gatewayMissing': 'Im Projekt nicht gefunden',
    'preview.buildings': '{count} Gebäude',
    'preview.floors': '{count} Etagen',
    'preview.rooms': '{count} Räume',
    'preview.addresses': '{count} Gruppenadressen',
    'preview.devices': '{count} Geräte',
    'preview.empty': 'Keine Gebäudestruktur vorhanden.',
    'stats.generatedFiles': 'Erzeugte Dateien',
    'stats.file': 'Datei',
    'stats.before': 'Vorher',
    'stats.after': 'Nachher',
    'stats.change': 'Änderung',
    'stats.diff': 'Diff',
    'stats.action': 'Aktion',
    'stats.noData': 'Keine Statistikdaten verfügbar.',
    'stats.displayError': 'Fehler beim Anzeigen der Statistik: {error}',
    'reports.expertTitle': 'Expertenberichte',
    'reports.none': 'Keine Berichte verfügbar.',
    'reports.noData': 'Keine Berichtsdaten verfügbar.',
    'reports.loading': 'Bericht wird geladen …',
    'reports.invalidJson': 'Bericht enthält kein gültiges JSON.',
    'reports.requiredMissing': 'Fehlende Pflichtangaben: {count}',
    'reports.recommendedMissing': 'Fehlende Empfehlungen: {count}',
    'reports.missingRequired': 'Fehlende Pflichtangaben',
    'reports.recommended': 'Empfohlen',
    'filePreview.loading': 'Datei wird geladen …',
    'filePreview.errorLoading': 'Fehler beim Laden der Datei: {error}{hint}',
    'filePreview.accessDenied': '\n\nHinweis: Diese Datei liegt nicht in einem erlaubten Pfad.',
    'filePreview.notFound': '\n\nHinweis: Die Datei existiert (noch) nicht.',
    'filePreview.diffLoadFailed': 'Diff konnte nicht geladen werden: {error}',
    'filePreview.reportDownloadFailed': 'Bericht konnte nicht heruntergeladen werden: {error}{hint}',
    'filePreview.reportCopied': 'Bericht in die Zwischenablage kopiert',
    'filePreview.copyFailed': 'Kopieren fehlgeschlagen: {error}{hint}',
    'service.active': 'Aktiv',
    'service.inactive': 'Inaktiv',
    'service.since': 'Seit:',
    'service.lastActive': 'Zuletzt aktiv:',
    'service.installed': 'Installiert:',
    'service.aptCandidate': 'APT-Kandidat:',
    'service.restart': 'Neu starten',
    'service.restarting': 'Wird neu gestartet …',
    'service.update': 'Aktualisieren',
    'service.noUpdate': 'Kein Update',
    'service.confirmUpdate': '{service} von {installed} auf den APT-Kandidaten {candidate} aktualisieren?',
    'service.packageStatus': '{action}: {message}',
    'service.action.refresh': 'Paketlisten aktualisieren',
    'service.action.openhab': 'OpenHAB aktualisieren',
    'service.action.evcc': 'evcc aktualisieren',
    'service.message.startingApt': 'APT wird gestartet …',
    'service.message.packageListsRefreshed': 'Paketlisten aktualisiert.',
    'service.message.packageUpdateFinished': 'Update für {package} abgeschlossen.',
    'service.message.aptFailed': 'APT-Vorgang fehlgeschlagen.',
    'service.message.notInstalled': 'APT-Paket ist auf diesem Host nicht installiert.',
    'service.message.infoUnavailable': 'APT-Paketinformationen sind nicht verfügbar.',
    'service.message.noCandidate': 'Für dieses Paket ist kein APT-Kandidat verfügbar.',
    'service.message.localCandidate': 'APT-Kandidat aus lokalen Paketlisten.',
    'service.message.infoUnreadable': 'APT-Paketinformationen konnten nicht gelesen werden.',
    'service.message.noUpdate': 'Für dieses Paket ist kein APT-Update verfügbar.',
    'service.message.candidateChanged': 'APT-Kandidat wurde geändert. Aktualisieren Sie die Ansicht und bestätigen Sie erneut.',
    'service.message.helperMissing': 'Update-Hilfsprogramm ist nicht installiert. Führen Sie einmal sudo bash installer/setup.sh aus.',
    'service.message.operationRunning': 'Ein anderer Paketvorgang wird bereits ausgeführt.',
    'service.message.operationStarted': 'Paketvorgang gestartet.',
    'service.message.unsupportedAction': 'Nicht unterstützte Aktion.',
    'service.statusUnavailable': 'Status nicht erreichbar: {error}',
    'service.operationFailed': 'Paketoperation fehlgeschlagen: {error}',
    'service.restartError': 'Fehler: {error}',
    'service.cloudTitle': 'openHAB-Cloud-Zugangsdaten',
    'service.cloudNotFound': 'UUID / Secret nicht gefunden.',
    'service.cloudExpected': 'Erwartet unter',
    'service.and': 'und',
    'service.cloudSetupHint': 'Für die Einrichtung auf myopenhab.org',
    'service.copyUuid': 'UUID kopieren',
    'service.showSecret': 'Secret anzeigen/verbergen',
    'service.copySecret': 'Secret kopieren',
    'rollback.running': 'Wiederherstellung läuft …',
    'rollback.success': '✓ Wiederherstellung erfolgreich: {output}',
    'rollback.error': '✗ Fehler: {error}',
    'job.deleteConfirm': 'Diesen Auftrag aus dem Verlauf löschen?',
    'job.deleteFailed': 'Löschen fehlgeschlagen: {error}',
    'job.deployConfirm': 'Wirklich bereitstellen? Die bestehende Konfiguration wird überschrieben!',
    'job.processing': 'Wird verarbeitet …',
    'job.deployed': 'Erfolgreich bereitgestellt: {message}',
    'job.deployError': 'Fehler beim Bereitstellen: {error}',
    'job.restartError': 'Fehler: {error}',
    'job.error': 'Fehler: {error}',
    'structure.loading': 'Struktur aus Auftrag wird geladen …',
    'structure.jobCompleted': 'Auftrag abgeschlossen, Struktur wird geladen …',
    'structure.retrieving': 'Strukturdaten werden abgerufen …',
    'structure.loaded': '✓ Struktur aus Auftragsverlauf geladen',
    'structure.error': '✗ Fehler: {error}',
    'structure.statusFailed': '✗ Auftragsstatus konnte nicht abgerufen werden (HTTP {status}).',
    'structure.jobFailed': '✗ Auftrag fehlgeschlagen: {error}',
    'structure.jobFailedUnknown': '✗ Auftrag fehlgeschlagen.',
    'structure.timeout': '✗ Auftrag wurde nicht innerhalb von {seconds} Sekunden abgeschlossen.',
    'structure.previewFailed': '✗ Struktur aus Auftrag konnte nicht geladen werden.',
    'updates.checkError': 'Fehler beim Suchen nach Updates: {error}',
    'updates.latest': '✓ Sie verwenden bereits die neueste Version!',
    'updates.checkFailed': 'Update-Prüfung fehlgeschlagen: {error}',
    'updates.starting': 'Update-Vorgang wird gestartet …\n',
    'updates.apiError': 'Fehler bei der Update-API: {error}\n',
    'updates.requestFailed': 'Anfrage fehlgeschlagen: {error}\n',
    'login.error.expired': 'Die Anmeldeanfrage ist abgelaufen. Bitte versuchen Sie es erneut.',
    'login.error.limited': 'Zu viele Versuche. Bitte versuchen Sie es später erneut.',
    'login.error.invalid': 'Benutzername oder Passwort ist falsch.',
    'login.error.unconfigured': 'Web-UI-Zugangsdaten sind nicht eingerichtet. Führen Sie installer/setup.sh als Administrator aus.'
  })
  Object.assign(catalogs.en, {
    'common.delete': 'Delete',
    'common.preview': 'Preview',
    'common.download': 'Download',
    'common.copy': 'Copy',
    'common.view': 'View',
    'config.loading': 'Loading configuration…',
    'config.loaded': '✓ Configuration loaded',
    'config.loadFailed': 'Failed to load configuration',
    'config.loadError': '✗ Error: {error}',
    'config.saving': 'Saving configuration…',
    'config.saved': '✓ Configuration saved',
    'config.saveError': '✗ Error: {error}',
    'config.saveFailed': 'Failed to save configuration',
    'config.noJob': 'No job selected to reprocess. Please select a job first.',
    'config.reprocessing': 'Triggering reprocessing…',
    'config.reprocessStarted': '✓ Reprocessing started (Job {id})',
    'config.reprocessFailed': '✗ Reprocessing failed: {error}',
    'preview.parseProject': 'Parsing project structure…',
    'preview.projectLoaded': '✓ Project structure loaded',
    'preview.error': '✗ Error: {error}',
    'preview.project': 'Project:',
    'preview.gatewayIp': 'Gateway IP:',
    'preview.totalAddresses': 'Total group addresses:',
    'preview.enabled': 'Enabled',
    'preview.disabled': 'Disabled',
    'preview.unknownItems': 'Unknown items:',
    'preview.found': 'found',
    'preview.gatewayMissing': 'Not found in project',
    'preview.buildings': '{count} buildings',
    'preview.floors': '{count} floors',
    'preview.rooms': '{count} rooms',
    'preview.addresses': '{count} group addresses',
    'preview.devices': '{count} devices',
    'preview.empty': 'No building structure available.',
    'stats.generatedFiles': 'Generated Files',
    'stats.file': 'File',
    'stats.before': 'Before',
    'stats.after': 'After',
    'stats.change': 'Change',
    'stats.diff': 'Diff',
    'stats.action': 'Action',
    'stats.noData': 'No statistics available.',
    'stats.displayError': 'Error displaying statistics: {error}',
    'reports.expertTitle': 'Expert Reports',
    'reports.none': 'No reports available.',
    'reports.noData': 'No report data available.',
    'reports.loading': 'Loading report…',
    'reports.invalidJson': 'Report is not valid JSON.',
    'reports.requiredMissing': 'Required missing: {count}',
    'reports.recommendedMissing': 'Recommended missing: {count}',
    'reports.missingRequired': 'Missing required',
    'reports.recommended': 'Recommended',
    'filePreview.loading': 'Loading file…',
    'filePreview.errorLoading': 'Error loading file: {error}{hint}',
    'filePreview.accessDenied': '\n\nHint: This file is outside the allowed paths.',
    'filePreview.notFound': '\n\nHint: The file does not (yet) exist.',
    'filePreview.diffLoadFailed': 'Failed to load diff: {error}',
    'filePreview.reportDownloadFailed': 'Report download failed: {error}{hint}',
    'filePreview.reportCopied': 'Report copied to clipboard',
    'filePreview.copyFailed': 'Copy failed: {error}{hint}',
    'service.active': 'Active',
    'service.inactive': 'Inactive',
    'service.since': 'Since:',
    'service.lastActive': 'Last active:',
    'service.installed': 'Installed:',
    'service.aptCandidate': 'APT candidate:',
    'service.restart': 'Restart',
    'service.restarting': 'Restarting…',
    'service.update': 'Update',
    'service.noUpdate': 'No update',
    'service.confirmUpdate': 'Update {service} from {installed} to APT candidate {candidate}?',
    'service.packageStatus': '{action}: {message}',
    'service.action.refresh': 'Refresh package lists',
    'service.action.openhab': 'Update OpenHAB',
    'service.action.evcc': 'Update evcc',
    'service.message.startingApt': 'Starting APT…',
    'service.message.packageListsRefreshed': 'Package lists refreshed.',
    'service.message.packageUpdateFinished': 'Update for {package} finished.',
    'service.message.aptFailed': 'APT operation failed.',
    'service.message.notInstalled': 'APT package is not installed on this host.',
    'service.message.infoUnavailable': 'APT package information is unavailable.',
    'service.message.noCandidate': 'No APT candidate is available for this package.',
    'service.message.localCandidate': 'APT candidate from local package lists.',
    'service.message.infoUnreadable': 'APT package information could not be read.',
    'service.message.noUpdate': 'No APT update is available for this package.',
    'service.message.candidateChanged': 'APT candidate changed. Refresh the view and confirm again.',
    'service.message.helperMissing': 'Update helper is not installed. Run sudo bash installer/setup.sh once.',
    'service.message.operationRunning': 'Another package operation is already running.',
    'service.message.operationStarted': 'Package operation started.',
    'service.message.unsupportedAction': 'Unsupported action.',
    'service.statusUnavailable': 'Status unavailable: {error}',
    'service.operationFailed': 'Package operation failed: {error}',
    'service.restartError': 'Error: {error}',
    'service.cloudTitle': 'openHAB Cloud Credentials',
    'service.cloudNotFound': 'UUID / Secret not found.',
    'service.cloudExpected': 'Expected at',
    'service.and': 'and',
    'service.cloudSetupHint': 'For setup at myopenhab.org',
    'service.copyUuid': 'Copy UUID',
    'service.showSecret': 'Show/hide secret',
    'service.copySecret': 'Copy secret',
    'rollback.running': 'Rolling back…',
    'rollback.success': '✓ Rollback successful: {output}',
    'rollback.error': '✗ Error: {error}',
    'job.deleteConfirm': 'Delete this job from history?',
    'job.deleteFailed': 'Delete failed: {error}',
    'job.deployConfirm': 'Really deploy? The existing configuration will be overwritten!',
    'job.processing': 'Processing…',
    'job.deployed': 'Successfully deployed: {message}',
    'job.deployError': 'Deploy error: {error}',
    'job.restartError': 'Error: {error}',
    'job.error': 'Error: {error}',
    'structure.loading': 'Loading structure from job…',
    'structure.jobCompleted': 'Job completed, loading structure…',
    'structure.retrieving': 'Retrieving structure data…',
    'structure.loaded': '✓ Structure loaded from job history',
    'structure.error': '✗ Error: {error}',
    'structure.statusFailed': '✗ Failed to retrieve job status (HTTP {status}).',
    'structure.jobFailed': '✗ Job failed: {error}',
    'structure.jobFailedUnknown': '✗ Job failed.',
    'structure.timeout': '✗ Job did not complete within {seconds} seconds.',
    'structure.previewFailed': '✗ Failed to load structure from job.',
    'updates.checkError': 'Error checking for updates: {error}',
    'updates.latest': '✓ You are running the latest version!',
    'updates.checkFailed': 'Failed to check for updates: {error}',
    'updates.starting': 'Starting update process…\n',
    'updates.apiError': 'Error interacting with update API: {error}\n',
    'updates.requestFailed': 'Request failed: {error}\n',
    'login.error.expired': 'The sign-in request expired. Please try again.',
    'login.error.limited': 'Too many attempts. Please try again later.',
    'login.error.invalid': 'Username or password is incorrect.',
    'login.error.unconfigured': 'Web UI credentials are not configured. Run installer/setup.sh as an administrator.'
  })
  const supportedLocales = Object.keys(catalogs)
  let currentLocale = 'de'

  function normalizeLocale(locale) {
    return supportedLocales.includes(locale) ? locale : 'de'
  }

  function readStoredLocale() {
    try {
      return window.localStorage.getItem(STORAGE_KEY)
    } catch (_error) {
      return null
    }
  }

  function t(key, params = {}) {
    const template = catalogs[currentLocale][key] ?? catalogs.de[key] ?? key
    return template.replace(/\{([^{}]+)\}/g, (match, name) => {
      return Object.prototype.hasOwnProperty.call(params, name) ? String(params[name]) : match
    })
  }

  function translateMessage(message) {
    if (typeof message !== 'string') return message

    const timestampMatch = message.match(/^(\[\d{1,2}:\d{2}:\d{2}\]\s*)/)
    const timestamp = timestampMatch ? timestampMatch[1] : ''
    const afterTimestamp = timestamp ? message.slice(timestamp.length) : message
    const categoryMatch = afterTimestamp.match(/^\[(BACKUP|STATUS|INFO|ERROR|WARNING|DEBUG|STATS|DONE)\]\s*/)
    const originalCategory = categoryMatch ? categoryMatch[1] : ''
    const categoryPrefix = categoryMatch ? categoryMatch[0] : ''
    const body = categoryMatch ? afterTimestamp.slice(categoryPrefix.length) : afterTimestamp
    let translated = null
    let match

    if ((match = body.match(/^backup created: (.+)$/i))) {
      translated = t('message.backupCreated', { filename: match[1] })
    } else if ((match = body.match(/^backup failed: (.+)$/i))) {
      translated = t('message.backupFailed', { error: match[1] })
    } else if ((match = body.match(/^retention error: (.+)$/i))) {
      translated = t('message.retentionError', { error: match[1] })
    } else if ((match = body.match(/^Staging directory: (.+)$/i))) {
      translated = t('message.stagingDirectory', { path: match[1] })
    } else if (/^start in-process generation$/i.test(body)) {
      translated = t('message.generationStarted')
    } else if (/^read project JSON dump$/i.test(body)) {
      translated = t('message.readJson')
    } else if (/^parsing knxproj archive \(this may take a while\)$/i.test(body)) {
      translated = t('message.parsingKnxproj')
    } else if (/^parsed knxproj$/i.test(body)) {
      translated = t('message.parsedKnxproj')
    } else if ((match = body.match(/^(\d+) addresses extracted$/i))) {
      translated = t('message.addressesExtracted', { count: match[1] })
    } else if ((match = body.match(/^project structure preview could not be saved: (.+)$/i))) {
      translated = t('message.previewSaveFailed', { error: match[1] })
    } else if (/^generating files \(staged\)\.\.\.$/i.test(body)) {
      translated = t('message.generatingStaged')
    } else if ((match = body.match(/^completeness report written: (.+)$/i))) {
      translated = t('message.completenessWritten', { path: match[1] })
    } else if ((match = body.match(/^completeness report failed: (.+)$/i))) {
      translated = t('message.completenessFailed', { error: match[1] })
    } else if (/^completed \(staged\) - ready to deploy$/i.test(body)) {
      translated = t('message.jobCompletedStaged')
    } else if (/^running$/i.test(body)) {
      translated = t('message.running')
    } else if (/^completed$/i.test(body)) {
      translated = t('message.completed')
    } else if (/^failed$/i.test(body)) {
      translated = t('message.failed')
    } else if (/^job finished$/i.test(body)) {
      translated = t('message.jobFinished')
    } else if ((match = body.match(/^stats error: (.+)$/i))) {
      translated = t('message.statsError', { error: match[1] })
    } else if (/^Starting APT…$/i.test(body)) {
      translated = t('service.message.startingApt')
    } else if (/^Package lists refreshed\.$/i.test(body)) {
      translated = t('service.message.packageListsRefreshed')
    } else if ((match = body.match(/^(openhab|evcc) update finished\.$/i))) {
      translated = t('service.message.packageUpdateFinished', { package: match[1] })
    } else if (/^APT operation failed\.$/i.test(body)) {
      translated = t('service.message.aptFailed')
    } else if (/^APT package is not installed on this host\.$/i.test(body)) {
      translated = t('service.message.notInstalled')
    } else if (/^APT package information is unavailable\.$/i.test(body)) {
      translated = t('service.message.infoUnavailable')
    } else if (/^No APT candidate is available for this package\.$/i.test(body)) {
      translated = t('service.message.noCandidate')
    } else if (/^APT candidate from local package lists\.$/i.test(body)) {
      translated = t('service.message.localCandidate')
    } else if (/^APT package information could not be read\.$/i.test(body)) {
      translated = t('service.message.infoUnreadable')
    } else if (/^No APT update is available for this package\.$/i.test(body)) {
      translated = t('service.message.noUpdate')
    } else if (/^APT candidate changed\. Refresh the view and confirm again\.$/i.test(body)) {
      translated = t('service.message.candidateChanged')
    } else if (/^Update helper is not installed\. Run sudo bash installer\/setup\.sh once\.$/i.test(body)) {
      translated = t('service.message.helperMissing')
    } else if (/^Another package operation is already running\.$/i.test(body)) {
      translated = t('service.message.operationRunning')
    } else if (/^Package operation started\.$/i.test(body)) {
      translated = t('service.message.operationStarted')
    } else if (/^Unsupported action\.$/i.test(body)) {
      translated = t('service.message.unsupportedAction')
    } else if (/^(No usable deployed KNX Things target|No usable successfully deployed KNX Things target is available)$/i.test(body)) {
      translated = t('gateway.error.noTarget')
    } else if ((match = body.match(/^Invalid IP address: (.+)$/i))) {
      translated = t('gateway.error.invalidIp', { address: match[1] })
    } else if (/^(A non-empty )?IP address is required$/i.test(body)) {
      translated = t('gateway.error.ipRequired')
    } else if (/^Generator gateway IP override must be a string$/i.test(body)) {
      translated = t('gateway.error.overrideType')
    } else {
      const statsMatch = body.match(/^(.+?): (\d+ -> \d+ lines? \([^)]+\) \[.+\])$/i)
      if (statsMatch) {
        const suffix = statsMatch[2].replace(/\blines?\b/i, currentLocale === 'de' ? 'Zeilen' : 'lines')
        translated = `${statsMatch[1]}: ${suffix}`
      }
    }

    if (translated === null) return message
    const translatedCategory = originalCategory
      ? `[${t(`log.category.${originalCategory.toLowerCase()}`)}] `
      : ''
    return `${timestamp}${translatedCategory}${translated}`
  }

  function translateElement(element) {
    if (element.dataset.i18n) {
      let params = {}
      try {
        params = JSON.parse(element.dataset.i18nParams || '{}')
      } catch (_error) {
        params = {}
      }
      element.textContent = t(element.dataset.i18n, params)
    }

    Array.from(element.attributes).forEach(attribute => {
      if (!attribute.name.startsWith('data-i18n-') || attribute.name === 'data-i18n-params') {
        return
      }
      const targetAttribute = attribute.name.slice('data-i18n-'.length)
      element.setAttribute(targetAttribute, t(attribute.value))
    })
  }

  function applyTranslations(root = document) {
    const translateIfMarked = element => {
      const hasTranslation = Array.from(element.attributes).some(attribute => {
        return attribute.name === 'data-i18n' ||
          (attribute.name.startsWith('data-i18n-') && attribute.name !== 'data-i18n-params')
      })
      if (hasTranslation) translateElement(element)
    }
    if (root instanceof Element) translateIfMarked(root)
    root.querySelectorAll('*').forEach(translateIfMarked)
  }

  function getLanguage() {
    return currentLocale
  }

  function setLanguage(locale) {
    currentLocale = normalizeLocale(locale)
    try {
      window.localStorage.setItem(STORAGE_KEY, currentLocale)
    } catch (_error) {
      // Continue with the in-memory locale when storage is unavailable.
    }

    document.documentElement.lang = currentLocale
    applyTranslations()
    const selector = document.getElementById('languageSelect')
    if (selector) selector.value = currentLocale
    document.dispatchEvent(new CustomEvent('knx-language-change', { detail: { locale: currentLocale } }))
    return currentLocale
  }

  function initialize() {
    currentLocale = normalizeLocale(readStoredLocale())
    document.documentElement.lang = currentLocale
    applyTranslations()

    const selector = document.getElementById('languageSelect')
    if (selector) {
      selector.value = currentLocale
      selector.addEventListener('change', () => setLanguage(selector.value))
    }
  }

  window.I18N = { catalogs, t, getLanguage, setLanguage, translateMessage }
  initialize()
})()
