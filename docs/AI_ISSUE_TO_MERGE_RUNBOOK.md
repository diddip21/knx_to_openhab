# Runbook: vom Issue zum geprueften Merge

Die verbindliche Beschreibung des allgemeinen Workflows steht unter
[AI_AUTOMATION.md](AI_AUTOMATION.md). Dieses bisher issue-spezifische Runbook
ist durch den allgemeinen Ablauf ersetzt.

Issue -> Plan -> Owner-Freigabe -> ausdruecklicher Dateiumfang -> Draft-PR
gegen `dev` -> CI -> hoechstens zwei Reparaturen -> Software-Pruefbericht
-> menschliches Review -> bewusster manueller Merge.

Kein Hardware-Stop-Gate, keine automatische Merge-Freigabe und keine
pauschalen Schreibrechte. Fehlende Nachweise bleiben OPEN. Lokale Tests mit
Git und pytest sowie simulierte GitHub-APIs sind getrennt von echten
OpenCode-/GitHub-Ende-zu-Ende-Laeufen auszuweisen.
