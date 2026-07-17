<!-- tools.md -->
# Carly Managed Backend: Tools und Befehle

## Virtuelle Umgebung

### Windows PowerShell

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
```

### Linux, WSL oder macOS

```bash
python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
```

## ENV-Dateien

Lokal wird ohne weitere Variable automatisch `.env.local` geladen.

```powershell
python manage.py check
```

Für Produktion muss die Umgebung vor dem Prozessstart explizit gesetzt werden.

```bash
export DJANGO_ENV=production
python manage.py check --deploy
```

Alternativ kann eine konkrete Datei erzwungen werden.

```bash
export CARLY_ENV_FILE=.env.prod
python manage.py check --deploy
```

Sichere Werte erzeugen:

```bash
python -c "import secrets; print(secrets.token_urlsafe(64))"
```

## PostgreSQL

Datenbank und Benutzer lokal anlegen:

```sql
CREATE DATABASE carly_managed;
CREATE USER carly_admin WITH PASSWORD '<PASSWORT_AUS_ENV_LOCAL>';
GRANT ALL PRIVILEGES ON DATABASE carly_managed TO carly_admin;
```

PostgreSQL-Konsole öffnen:

```bash
psql -U carly_admin -d carly_managed -h 127.0.0.1
```

Wichtige psql-Befehle:

```text
\du
\l
\dt
\q
```

## Redis oder Memurai

Für Windows-Entwicklung wird Memurai empfohlen. Dienststatus prüfen:

```powershell
sc.exe query memurai
netstat -ano | findstr :6379
```

Verbindung testen:

```powershell
memurai-cli.exe
AUTH <REDIS_PASSWORD_AUS_ENV_LOCAL>
PING
```

Erwartete Antwort:

```text
PONG
```

Unter Linux oder WSL:

```bash
sudo systemctl status redis-server
sudo systemctl start redis-server
redis-cli -a '<REDIS_PASSWORD>' ping
```

## Datenbank und Django

Migrationen erstellen und anwenden:

```bash
python manage.py makemigrations
python manage.py migrate
```

Vor produktiven Migrationen immer ein Datenbank-Backup erstellen.

Administratorkonto anlegen:

```bash
python manage.py createsuperuser
```

Statische Dateien sammeln:

```bash
python manage.py collectstatic --noinput
```

Django-Konfiguration prüfen:

```bash
python manage.py check
python manage.py check --deploy --settings=config.settings.production
```

## Server und Hintergrundprozesse

Daphne starten:

```bash
daphne -b 127.0.0.1 -p 8000 config.asgi:application
```

Celery Worker starten:

```bash
python -m celery -A config worker --loglevel=INFO --concurrency=1
```

Celery Beat starten:

```bash
python -m celery -A config beat --loglevel=INFO
```

Für Windows muss der Worker mit Solo-Pool laufen:

```powershell
python -m celery -A config worker --loglevel=INFO --pool=solo --concurrency=1
```

## Docker Compose

Lokale Umgebung starten:

```bash
docker compose --env-file .env.local up --build
```

Produktive ENV-Konfiguration verwenden:

```bash
docker compose --env-file .env.prod up --build -d
```

Containerstatus und Logs:

```bash
docker compose ps
docker compose logs -f api
docker compose logs -f worker
docker compose logs -f beat
```

Container stoppen:

```bash
docker compose down
```

Datenvolumes zusätzlich löschen:

```bash
docker compose down -v
```

## Tests und Qualität

Vollständige Tests mit Branch-Coverage:

```bash
pytest --cov --cov-report=term-missing
```

Formatierung prüfen oder anwenden:

```bash
ruff format --check .
ruff format .
```

Linting:

```bash
ruff check .
ruff check . --fix
```

Migrationen auf fehlende Änderungen prüfen:

```bash
python manage.py makemigrations --check --dry-run
```

OpenAPI neu erzeugen und validieren:

```bash
python manage.py spectacular --file docs/openapi.yml --validate
```

Security-Prüfungen:

```bash
bandit -q -r apps config -x "*/tests/*,*/migrations/*" -c pyproject.toml
pip-audit -r requirements.txt
```

## API-Schnelltests

Health-Endpunkt:

```bash
curl -i http://127.0.0.1:8000/api/v1/health/
```

Swagger UI:

```text
http://127.0.0.1:8000/api/docs/
```

Admin:

```text
http://127.0.0.1:8000/admin/
```

## Systemd: Produktion

API-Service öffnen:

```bash
sudo nano /etc/systemd/system/carly-managed-api.service
```

Wichtige Service-Werte:

```ini
[Service]
WorkingDirectory=/home/users/carly-managed-backend
Environment=DJANGO_ENV=production
ExecStart=/home/users/carly-managed-backend/.venv/bin/daphne -b 127.0.0.1 -p 8000 config.asgi:application
Restart=always
```

Service aktivieren und prüfen:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now carly-managed-api
sudo systemctl restart carly-managed-api
sudo systemctl status carly-managed-api
journalctl -u carly-managed-api -n 100 --no-pager
```

Für Worker und Beat sollten separate Services mit denselben ENV- und Arbeitsverzeichniswerten angelegt werden.

## Abhängigkeiten aktualisieren

Installierte Versionen anzeigen:

```bash
python -m pip list --outdated
```

`requirements.txt` und `pyproject.toml` müssen bei Versionsänderungen gemeinsam aktualisiert werden. Kein ungeprüftes `pip freeze` über die Projektdateien schreiben.

## Git

Lokalen Stand auf den Remote-Stand zurücksetzen:

```bash
git fetch origin
git reset --hard origin/main
```