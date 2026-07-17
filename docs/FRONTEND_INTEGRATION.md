<!-- docs/FRONTEND_INTEGRATION.md -->
# Angular-Integration

## Basis-URLs

- REST: `/api/v1/`
- Workspace-Domäne: `/api/v1/workspaces/`
- Inbox: `/api/v1/inbox/`
- Präferenzen: `/api/v1/preferences/`
- Board-WebSocket: `/ws/v1/boards/<board-id>/`
- Inbox-WebSocket: `/ws/v1/inbox/`
- OpenAPI: `/api/schema/`

## Anmeldung und CSRF

Angular muss Requests mit `withCredentials: true` senden. Vor dem ersten schreibenden Request wird `/api/v1/auth/csrf/` aufgerufen. Ein HTTP-Interceptor liest anschließend das Cookie `cm_csrftoken` und setzt bei `POST`, `PUT`, `PATCH` und `DELETE` den Header `X-CSRFToken`.

Die Sitzung selbst liegt ausschließlich im sicheren, nicht per JavaScript lesbaren Cookie `cm_session`. Es werden keine Access- oder Refresh-Tokens im Browser-Speicher benötigt.

## Empfohlene Umstellung des Preview-Frontends

Die vorhandenen Preview-Services verwenden teilweise `localStorage`. Sie sollten schrittweise durch folgende Adapter ersetzt werden:

1. `AuthService` auf `/api/v1/auth/*`
2. Workspace- und Projektzugriff auf `/api/v1/workspaces/`, `/projects/` und `/boards/`
3. Task-Aktionen auf `/api/v1/workspaces/tasks/`
4. Inbox auf `/api/v1/inbox/notifications/` und `/conversations/`
5. Einstellungen auf `/api/v1/preferences/settings/` und `/carly/`
6. Live-Funktionen auf die Board- und Inbox-WebSockets

Die exakten Request- und Response-Typen können aus `docs/openapi.yml` generiert werden.

## Versionskonflikte

Bei Änderungen wird die zuletzt gelesene `version` mitgesendet. HTTP 409 bedeutet, dass die Ressource zwischenzeitlich geändert wurde. Beispiel:

```json
{
  "code": "version_conflict",
  "message": "Die Ressource wurde zwischenzeitlich geändert.",
  "details": {
    "currentVersion": "3"
  }
}
```

Das Frontend sollte den aktuellen Datensatz neu laden und einen sichtbaren Konflikthinweis anbieten, statt die neue Serverversion still zu überschreiben.

## Validierungsfehler

```json
{
  "code": "validation_error",
  "message": "Bitte prüfe die markierten Eingaben.",
  "fields": {
    "email": [
      {
        "code": "invalid",
        "message": "Gib eine gültige E-Mail-Adresse ein."
      }
    ]
  }
}
```

Fehler dürfen in der UI nicht ausschließlich über Farbe vermittelt werden. Text, Icon, Fokusführung und passende ARIA-Verknüpfungen sollten gemeinsam eingesetzt werden.

## WebSocket-Ereignisse

Board-Verbindungen akzeptieren ausschließlich Ereignistypen, die der Server explizit kennt. Präsenz, Cursor und Bearbeitungshinweise sind flüchtig und werden nicht als Geschäftsdaten persistiert. Dauerhafte Task-Änderungen erfolgen weiterhin über REST; anschließend kann das Frontend das Ergebnis als Live-Ereignis an andere verbundene Clients verteilen.
