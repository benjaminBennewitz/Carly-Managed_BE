<!-- README.md -->
# Carly Managed Backend

Produktionsnahes Django-Backend für das Angular-Frontend **Carly Managed**. Der Quellcode folgt PEP 8; Module, Klassen und öffentliche Funktionen sind mit deutschen Docstrings nach PEP 257 dokumentiert.

## Technischer Stack

- Python 3.13
- Django 5.2 LTS und Django REST Framework
- PostgreSQL für dauerhafte Geschäftsdaten
- Redis für Cache, Channels und Celery
- Django Channels mit Daphne für WebSockets
- Celery Worker und Celery Beat für Wiederholungen und Wartungsaufgaben

## Enthaltene Domänen

- Sichere Registrierung, E-Mail-Verifizierung, Anmeldung und Passwort-Wiederherstellung
- Workspaces, Mitglieder, Rollen, Projekte und Projektbeteiligte
- Persönliche und projektbezogene Boards, Spalten, Tasks und Unteraufgaben
- Kommentare, Erwähnungen, private Anhänge, Wiederholungen und Automationen
- Optimistische Versionskontrolle gegen unbemerkte parallele Überschreibungen
- Einladungen und Beitrittsanfragen
- Inbox, Systembenachrichtigungen, Gespräche und Chat-Nachrichten
- Nutzerpräferenzen, Barrierefreiheit und Carly-Fortschritt
- WebSockets für Präsenz, Live-Cursor, Bearbeitungshinweise und Inbox-Ereignisse
- Celery-Aufgaben für Wiederholungen, Einladungsablauf und Carly-Streaks
- OpenAPI-Schema, Swagger UI, Health-Endpunkte und stabile Fehlerantworten

## Lokaler Start mit Docker

1. Die mitgelieferte `.env.local` prüfen und bei Bedarf PostgreSQL- sowie Redis-Zugangsdaten anpassen.
2. Container mit der lokalen ENV-Datei starten:

```bash
docker compose --env-file .env.local up --build
```

3. Administratorkonto anlegen:

```bash
docker compose exec api python manage.py createsuperuser
```

Migrationen und statische Dateien werden beim Start des API-Containers vorbereitet. Die API läuft anschließend unter `http://localhost:8000/api/v1/`, die Swagger UI unter `http://localhost:8000/api/docs/`.

## Lokaler Start ohne Docker

### Windows PowerShell

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
python manage.py migrate
python manage.py runserver
```

### Linux oder macOS

```bash
python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
python manage.py migrate
python manage.py runserver
```

PostgreSQL und Redis müssen bei einem Start ohne Docker separat erreichbar sein. Lokal wird automatisch `.env.local` mit `config.settings.development` geladen. Für Produktion muss der Prozess `DJANGO_ENV=production` setzen; dann wird `.env.prod` mit `config.settings.production` verwendet. Zugangsdaten aus beiden Dateien dürfen nicht in Git eingecheckt werden.

Die produktiven Platzhalter in `.env.prod` sind absichtlich nicht startfähig. Django verweigert den Produktionsstart, solange Secrets, Hosts, HTTPS-Origins, Redis-, Datenbank- oder SMTP-Zugangsdaten nicht ersetzt wurden.

## Zusätzliche Prozesse

```bash
celery -A config worker --loglevel=INFO
celery -A config beat --loglevel=INFO
daphne -b 0.0.0.0 -p 8000 config.asgi:application
```

## Tests und Qualitätsprüfungen

```bash
pytest --cov --cov-report=term-missing
ruff check .
ruff format --check .
python manage.py makemigrations --check --dry-run
python manage.py spectacular --file docs/openapi.yml --validate
bandit -q -r apps config -x "*/tests/*,*/migrations/*" -c pyproject.toml
```

Der aktuelle CI-Mindestwert für die gesamte Branch-Coverage beträgt 65 Prozent. Kritische Sicherheits- und Autorisierungspfade werden zusätzlich durch Integrationstests abgedeckt.

## Session-Authentifizierung im Angular-Frontend

1. `GET /api/v1/auth/csrf/` mit `withCredentials: true` aufrufen.
2. Das Cookie `cm_csrftoken` auslesen.
3. Bei `POST`, `PUT`, `PATCH` und `DELETE` den Header `X-CSRFToken` mitsenden.
4. Alle REST- und WebSocket-Aufrufe mit denselben Cookies ausführen.
5. Keine Sitzungs- oder Anmeldetokens in `localStorage` speichern.

Die konkreten Datenverträge und Migrationsschritte stehen unter `docs/` und in `docs/openapi.yml`.
