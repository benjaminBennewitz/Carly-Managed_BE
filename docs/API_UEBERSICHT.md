<!-- docs/API_UEBERSICHT.md -->
# API-Übersicht

Alle fachlichen REST-Endpunkte liegen unter `/api/v1/`. Die vollständige, maschinenlesbare Spezifikation befindet sich in `docs/openapi.yml` und wird zusätzlich über `GET /api/schema/` bereitgestellt.

## Authentifizierung

- `GET /api/v1/auth/csrf/`
- `POST /api/v1/auth/register/`
- `POST /api/v1/auth/login/`
- `POST /api/v1/auth/logout/`
- `GET/PATCH /api/v1/auth/me/`
- `POST /api/v1/auth/password/change/`
- `POST /api/v1/auth/password/reset/request/`
- `POST /api/v1/auth/password/reset/confirm/`
- `POST /api/v1/auth/email/verify/request/`
- `POST /api/v1/auth/email/verify/confirm/`

## Workspaces, Projekte und Boards

- `/api/v1/workspaces/`
- `/api/v1/workspaces/<workspace-id>/members/`
- `/api/v1/workspaces/projects/`
- `/api/v1/workspaces/boards/`
- `/api/v1/workspaces/columns/`
- `/api/v1/workspaces/tasks/`
- `/api/v1/workspaces/automations/`
- `/api/v1/workspaces/invitations/`
- `/api/v1/workspaces/join-requests/`
- `/api/v1/workspaces/dashboard/`
- `/api/v1/workspaces/search/?q=<suchtext>`

Task-Aktionen wie Verschieben, Abschließen, Archivieren, Unteraufgaben, Kommentare, Anhänge und Wiederholungen werden als Detailaktionen unter `/api/v1/workspaces/tasks/<task-id>/.../` bereitgestellt.

## Inbox und Präferenzen

- `/api/v1/inbox/notifications/`
- `/api/v1/inbox/conversations/`
- `/api/v1/preferences/settings/`
- `/api/v1/preferences/carly/`
- `/api/v1/preferences/carly/actions/<action>/`

## System

- `GET /api/v1/health/`
- `GET /api/v1/ready/`
- `GET /api/schema/`
- `GET /api/docs/`

## WebSockets

- `/ws/v1/boards/<board-id>/`
- `/ws/v1/inbox/`

Die WebSocket-Verbindungen verwenden dieselbe authentifizierte Django-Sitzung wie die REST-API.


## Demo-Daten

- `GET /api/v1/demo/status/`
- `POST /api/v1/demo/reset/`

Der Reset ist standardmäßig nur lokal, ausschließlich für Staff-Konten und höchstens zweimal pro Minute verfügbar. Für geplante nächtliche Resets wird `python manage.py reset_demo_data` verwendet. Das Management-Command verwendet ohne E-Mail nur dann automatisch einen Owner, wenn exakt ein aktives Staff-Konto existiert.
