<!-- README.md -->
# Carly Managed Backend

Produktionsnahes Django-Backend für das Angular-Frontend **Carly Managed**. Der Quellcode folgt PEP 8; Module, Klassen und öffentliche Funktionen besitzen deutsche Docstrings nach PEP 257.

## Technischer Stack

- Python 3.13
- Django 5.2 LTS und Django REST Framework
- PostgreSQL für dauerhafte Geschäftsdaten
- Redis beziehungsweise Memurai für Cache, Channels und Celery
- Django Channels mit Daphne für WebSockets
- Celery Worker und Celery Beat für Wiederholungen und Wartungsaufgaben

## Enthaltene Domänen

- Registrierung, E-Mail-Verifizierung, Session-Login und Passwort-Wiederherstellung
- Workspaces, Mitglieder, Rollen, Projekte und Projektbeteiligte
- Persönliche und projektbezogene Boards, Spalten, Tasks und Unteraufgaben
- Kommentare, private Anhänge, Wiederholungen, Automationen und Historie
- Optimistische Versionskontrolle gegen unbemerkte parallele Überschreibungen
- Einladungen, Beitrittsanfragen, Inbox, Benachrichtigungen und Gespräche
- Nutzerpräferenzen, Barrierefreiheit und Carly-Fortschritt
- WebSockets für Präsenz, Live-Cursor, Bearbeitungshinweise und Inbox-Ereignisse
- Deterministische Demo-Daten mit manuellem und nächtlichem Reset

## Lokale Entwicklung unter Windows

Die folgenden Befehle werden in der klassischen Eingabeaufforderung ausgeführt:

```cmd
cd /d "C:\Pfad\zu\Carly-Managed_BE"
py -3.13 -m venv .venv
.venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
python manage.py migrate
python manage.py createsuperuser
```

PostgreSQL und Memurai müssen separat laufen. Lokal lädt das Backend automatisch `.env.local` und `config.settings.development`.

Daphne starten:

```cmd
daphne -b localhost -p 8000 config.asgi:application
```

Das Angular-Frontend läuft in der Entwicklung über den Proxy auf `http://localhost:4555`. Die API ist unter `http://localhost:8000/api/v1/`, Swagger unter `http://localhost:8000/api/docs/` erreichbar.

## Demo-Daten erzeugen

In `.env.local` aktivieren:

```env
DEMO_DATA_RESET_ENABLED=true
DEMO_DATA_RESET_ALLOW_PRODUCTION=false
DEMO_OWNER_EMAIL=deine-staff-email@example.com
DEMO_WORKSPACE_NAME=Carly Managed Demo
```

Anschließend den reproduzierbaren Datenbankstand erzeugen. Existiert genau ein aktives Staff-Konto, genügt:

```cmd
python manage.py reset_demo_data
```

Bei mehreren Staff-Konten wird der Owner ausdrücklich angegeben:

```cmd
python manage.py reset_demo_data --owner-email "deine-staff-email@example.com"
```

Der Reset ersetzt ausschließlich den benannten Demo-Workspace dieses Staff-Kontos. Andere Workspaces und Benutzerkonten bleiben erhalten. Persönliche App-Einstellungen und Carly-Zustand des Demo-Owners werden auf den definierten Ausgangsstand gesetzt.

Der gleiche Reset ist für Staff-Konten unter **Einstellungen → Testdaten** verfügbar.

## Nächtlichen Reset einrichten

Geplante Windows-Aufgabe für täglich 02:00 Uhr anlegen:

```cmd
scripts\install-demo-reset-task.cmd 02:00
```

Aufgabe sofort testen und Status prüfen:

```cmd
schtasks /Run /TN "Carly Managed Demo Reset"
schtasks /Query /TN "Carly Managed Demo Reset" /V /FO LIST
```

Protokoll:

```text
logs\demo-reset.log
```

Geplante Aufgabe entfernen:

```cmd
scripts\remove-demo-reset-task.cmd
```

## Zusätzliche Prozesse

Celery Worker unter Windows:

```cmd
python -m celery -A config worker --loglevel=INFO --pool=solo --concurrency=1
```

Celery Beat:

```cmd
python -m celery -A config beat --loglevel=INFO
```

## Tests und Qualitätsprüfungen

```cmd
pytest --cov --cov-report=term-missing
ruff check .
ruff format --check .
python manage.py makemigrations --check --dry-run
python manage.py spectacular --file docs\openapi.yml --validate
bandit -q -r apps config -x "*/tests/*,*/migrations/*" -c pyproject.toml
```

## Session-Authentifizierung im Angular-Frontend

1. `GET /api/v1/auth/csrf/` setzt das lesbare CSRF-Cookie.
2. Das HttpOnly-Sitzungscookie wird durch den Browser verwaltet.
3. Schreibende Requests senden `X-CSRFToken` und `withCredentials: true`.
4. Der Angular-Entwicklungsproxy leitet `/api`, `/ws` und `/media` an Port 8000 weiter.
5. Sitzungs- oder Anmeldetokens werden nicht im `localStorage` gespeichert.

Weitere Datenverträge und Sicherheitsentscheidungen stehen unter `docs/` und in `docs/openapi.yml`.
