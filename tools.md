<!-- tools.md -->
# Carly Managed Backend: Tools und Befehle

Alle Windows-Befehle werden in **CMD** ausgeführt. Nur Memurai wird wie gekennzeichnet über PowerShell geprüft.

## Projekt und virtuelle Umgebung

```cmd
cd /d "C:\Pfad\zu\Carly-Managed_BE"
py -3.13 -m venv .venv
.venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
```

Virtuelle Umgebung verlassen:

```cmd
deactivate
```

## ENV-Dateien

Lokal wird automatisch `.env.local` geladen:

```cmd
python manage.py check
```

Produktion im aktuellen CMD-Fenster aktivieren:

```cmd
set DJANGO_ENV=production
python manage.py check --deploy
```

Variable wieder entfernen:

```cmd
set DJANGO_ENV=
```

Sicheren Zufallswert erzeugen:

```cmd
python -c "import secrets; print(secrets.token_urlsafe(64))"
```

## PostgreSQL 16

Konsole als Administrator öffnen:

```cmd
"C:\Program Files\PostgreSQL\16\bin\psql.exe" -U postgres -h 127.0.0.1 -p 5432 -d postgres
```

Rolle und Datenbank anlegen:

```sql
CREATE ROLE carly_admin WITH LOGIN PASSWORD '<PASSWORT_AUS_ENV_LOCAL>';
CREATE DATABASE carly_managed OWNER carly_admin ENCODING 'UTF8';
GRANT ALL PRIVILEGES ON DATABASE carly_managed TO carly_admin;
```

Direkte Verbindung testen:

```cmd
set "PGPASSWORD=<PASSWORT_AUS_ENV_LOCAL>"
"C:\Program Files\PostgreSQL\16\bin\psql.exe" -U carly_admin -h 127.0.0.1 -p 5432 -d carly_managed -c "SELECT current_user, current_database(), version();"
set "PGPASSWORD="
```

Wichtige psql-Befehle:

```text
\du
\l
\dt
\q
```

## Memurai unter Windows – PowerShell

```powershell
sc.exe query memurai
netstat -ano | findstr :6379
memurai-cli.exe
```

In der Memurai-Konsole:

```text
AUTH <REDIS_PASSWORD_AUS_ENV_LOCAL>
PING
```

Erwartet wird `PONG`.

## Django und Datenbank

```cmd
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py migrate
python manage.py showmigrations
python manage.py createsuperuser
```

Statische Dateien:

```cmd
python manage.py collectstatic --noinput
```

## Server und Hintergrundprozesse

Daphne:

```cmd
daphne -b localhost -p 8000 config.asgi:application
```

Celery Worker unter Windows:

```cmd
python -m celery -A config worker --loglevel=INFO --pool=solo --concurrency=1
```

Celery Beat:

```cmd
python -m celery -A config beat --loglevel=INFO
```

## Demo-Daten

Einmaligen Ausgangsstand bei genau einem aktiven Staff-Konto erzeugen:

```cmd
python manage.py reset_demo_data
```

Bei mehreren Staff-Konten den Owner angeben:

```cmd
python manage.py reset_demo_data --owner-email "deine-staff-email@example.com"
```

Alternativ `DEMO_OWNER_EMAIL` in `.env.local` setzen:

```cmd
scripts\reset-demo-data.cmd
```

Nächtliche Windows-Aufgabe um 02:00 Uhr installieren:

```cmd
scripts\install-demo-reset-task.cmd 02:00
```

Aufgabe sofort ausführen:

```cmd
schtasks /Run /TN "Carly Managed Demo Reset"
```

Status anzeigen:

```cmd
schtasks /Query /TN "Carly Managed Demo Reset" /V /FO LIST
```

Logdatei anzeigen:

```cmd
type logs\demo-reset.log
```

Geplante Aufgabe entfernen:

```cmd
scripts\remove-demo-reset-task.cmd
```

## Tests und Qualität

```cmd
pytest --cov --cov-report=term-missing
ruff check .
ruff format --check .
python manage.py makemigrations --check --dry-run
python manage.py spectacular --file docs\openapi.yml --validate
bandit -q -r apps config -x "*/tests/*,*/migrations/*" -c pyproject.toml
```

## API-Schnelltests

```cmd
curl -i http://localhost:8000/api/v1/health/
```

```text
Swagger: http://localhost:8000/api/docs/
Admin:   http://localhost:8000/admin/
Frontend: http://localhost:4555/
```

## Docker Compose

```cmd
docker compose --env-file .env.local up --build
docker compose ps
docker compose logs -f api
docker compose down
```

## Git

```cmd
git status
git log --oneline --decorate --graph
git push
```
