<!-- docs/QUALITAETSBERICHT.md -->
# Qualitätsbericht – Version 1.0.0

Stand: 17. Juli 2026

## Automatisch geprüft

- Django-Systemcheck: keine Fehler
- Produktiver Django-Deployment-Check: keine Fehler oder Warnungen
- Migrationen: vollständig, keine nicht erzeugten Modelländerungen
- Ruff-Formatierung: vollständig formatiert
- Ruff-Linting: keine Befunde
- Bandit-Sicherheitsanalyse: keine Befunde mittlerer oder hoher Relevanz
- OpenAPI-Generierung und Validierung: keine Fehler oder Warnungen
- Docker-Compose-Datei: syntaktisch gültig
- Pytest: 28 Tests erfolgreich
- Branch-Coverage: 66,42 Prozent bei einem CI-Mindestwert von 65 Prozent

## Abgedeckte Sicherheitspfade

- CSRF-Pflicht für öffentliche schreibende Auth-Endpunkte
- Passwortregeln und Datenschutzzustimmung bei Registrierung
- generische Antworten gegen Kontoenumeration
- wirksame zeitliche Kontosperre nach wiederholten Fehlversuchen
- gehashte, ablaufende und einmalig nutzbare Konto-Tokens
- Queryset-basierter IDOR-Schutz für Boards, Tasks, Inbox und Dateien
- Rollenprüfung für strukturelle Workspace- und Projektänderungen
- optimistische Versionskontrolle gegen Lost Updates
- private Dateidownloads mit MIME-Sniffing-Schutz
- serverseitige Carly-Cooldowns und Tageslimits
- WebSocket-Authentifizierung und Ereignisvalidierung

## Infrastrukturelle Grenzen

Ein Online-Abgleich über `pip-audit` konnte in der isolierten Build-Umgebung wegen fehlender externer DNS-Auflösung nicht abgeschlossen werden. Das Projekt enthält exakte Abhängigkeitsversionen, Dependabot-Konfiguration und den lokalen Audit-Befehl. Vor einem produktiven Release sollte der Audit in einer Umgebung mit Internetzugriff erneut ausgeführt werden.

Malware-Scanning für Uploads, produktives SMTP, Secret-Rotation, Backups, Monitoring und Object Storage bleiben Deployment-Aufgaben.
