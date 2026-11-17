# KI-Workflow: Issue, Freigabe und gepruefter Merge

Der allgemeine Ablauf und die exakten Startbefehle stehen im
[aktuellen Runbook](AI_AUTOMATION.md). Fuer neue Issues werden keine eigenen
Controller oder Agenten mehr angelegt.

Erst Infrastruktur pruefen und bewusst nach `main` mergen, danach `dev`
synchronisieren. Plan freigeben, Bot-Bestaetigung abwarten und den
Implementierungsbefehl mit konkreten `files`/`create`/`required`-Listen posten.
CI, maximal zwei begrenzte Reparaturen und Software-Pruefbericht folgen.
Der Merge bleibt manuell; ein Hardwaretest ist kein Pflicht-Gate.

#108 bleibt als Vergleich erhalten. Alte scope-lose Befehle werden nicht
stillschweigend freigegeben; fuer den neuen Test ist ein neuer Plan erforderlich.
