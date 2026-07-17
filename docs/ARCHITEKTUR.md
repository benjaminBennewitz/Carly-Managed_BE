<!-- docs/ARCHITEKTUR.md -->
# Architektur

## Zielbild

Carly Managed trennt dauerhafte Geschäftsdaten und flüchtige Echtzeitdaten konsequent:

- REST und PostgreSQL verwalten Konten, Workspaces, Projekte, Boards, Tasks, Kommentare, Anhänge, Einladungen, Inbox und Einstellungen.
- WebSockets und Redis übertragen Präsenz, Live-Cursor, aktive Bearbeitungen und kurzfristige UI-Ereignisse.
- Celery verarbeitet zeitgesteuerte Wiederholungen und Wartungsaufgaben außerhalb des Request-Zyklus.

## Anwendungen

| Anwendung | Verantwortung |
|---|---|
| `accounts` | Benutzer, Session-Login, Registrierung, Verifizierung und Passwortprozesse |
| `workspaces` | Workspaces, Projekte, Boards, Tasks, Rollen und Einladungen |
| `inbox` | Benachrichtigungen, Konversationen und Nachrichten |
| `preferences` | UI-Einstellungen, Barrierefreiheit und Carly-Zustand |
| `realtime` | Autorisierte WebSocket-Verbindungen und flüchtige Events |
| `common` | Basismodelle, Fehlerformat, Pagination, Throttling und Validierung |

## Berechtigungsmodell

Workspace-Mitgliedschaften verwenden die Rollen `owner`, `manager` und `member`. Schreiboperationen prüfen stets die Mitgliedschaft sowie gegebenenfalls die konkrete Projekt- oder Board-Zuordnung. Querysets werden bereits auf erlaubte Ressourcen begrenzt, damit fremde UUIDs keine Daten offenlegen.

## Konflikterkennung

Veränderliche Ressourcen besitzen eine serverseitige Versionsnummer. Schreiboperationen müssen die erwartete Version mitsenden. Weicht sie vom aktuellen Stand ab, antwortet die API mit HTTP 409 und verhindert ein unbemerktes Überschreiben.

## Dateien

Anhänge sind keine frei erreichbaren Media-URLs. Der Download erfolgt über einen autorisierten Endpunkt, der die Workspace-Berechtigung erneut prüft und den Dateinamen sicher als Content-Disposition setzt.
