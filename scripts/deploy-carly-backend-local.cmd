@echo off
REM scripts/deploy-carly-backend-local.cmd
setlocal EnableExtensions

REM Testet das Backend lokal, erzeugt aus dem sauberen Git-Stand ein Release-Archiv
REM und startet anschließend das vorbereitete serverseitige Deployment.

set "SERVER=ben@159.195.54.12"
set "PYTHON=.venv\Scripts\python.exe"
set "ARCHIVE=%TEMP%\carly-managed-backend.tar.gz"
set "REMOTE_ARCHIVE=/tmp/carly-managed-backend.tar.gz"
set "REMOTE_DEPLOY=/usr/local/bin/deploy-carly-backend"

if defined CARLY_SSH_KEY (
  set "SSH_KEY=%CARLY_SSH_KEY%"
) else if defined DCR_SSH_KEY (
  set "SSH_KEY=%DCR_SSH_KEY%"
) else (
  set "SSH_KEY=%USERPROFILE%\.ssh\dcr_vserver_werbung06"
)

if not exist "%SSH_KEY%" (
  echo [CARLY][BE][FEHLER] SSH-Key nicht gefunden: %SSH_KEY%
  echo [CARLY][BE] Optional CARLY_SSH_KEY oder DCR_SSH_KEY setzen.
  exit /b 1
)

if not exist "%PYTHON%" (
  echo [CARLY][BE][FEHLER] Virtuelle Umgebung fehlt: %PYTHON%
  exit /b 1
)

where git >nul 2>&1 || (
  echo [CARLY][BE][FEHLER] git wurde nicht gefunden.
  exit /b 1
)

where scp >nul 2>&1 || (
  echo [CARLY][BE][FEHLER] scp wurde nicht gefunden.
  exit /b 1
)

where ssh >nul 2>&1 || (
  echo [CARLY][BE][FEHLER] ssh wurde nicht gefunden.
  exit /b 1
)

git rev-parse --show-toplevel >nul 2>&1 || (
  echo [CARLY][BE][FEHLER] Das Script muss aus dem Carly-Backend-Git-Repository gestartet werden.
  exit /b 1
)

set "GIT_DIRTY="
for /f "delims=" %%I in ('git status --porcelain') do set "GIT_DIRTY=1"

if defined GIT_DIRTY (
  echo [CARLY][BE][FEHLER] Git-Working-Tree ist nicht sauber. Deployment abgebrochen.
  git status --short
  exit /b 1
)

echo [CARLY][BE] Repository aktualisieren...
git pull --ff-only || exit /b 1

echo [CARLY][BE] Entwicklungs- und Testabhaengigkeiten synchronisieren...
"%PYTHON%" -m pip install --disable-pip-version-check -r requirements-dev.txt || exit /b 1

echo [CARLY][BE] Python-Abhaengigkeiten pruefen...
"%PYTHON%" -m pip check || exit /b 1

echo [CARLY][BE] Django-Systemcheck...
"%PYTHON%" manage.py check || exit /b 1

echo [CARLY][BE] Tests ausfuehren...
"%PYTHON%" -m pytest --cov --cov-report=term-missing || exit /b 1

echo [CARLY][BE] Ruff-Linting...
"%PYTHON%" -m ruff check . || exit /b 1

echo [CARLY][BE] Ruff-Formatcheck...
"%PYTHON%" -m ruff format --check . || exit /b 1

echo [CARLY][BE] Bandit-Securitycheck...
"%PYTHON%" -m bandit -q -r apps config -x "*/tests/*,*/migrations/*" -c pyproject.toml || exit /b 1

for /f %%I in ('git rev-parse --short^=12 HEAD') do set "RELEASE_ID=%%I"

if not defined RELEASE_ID (
  echo [CARLY][BE][FEHLER] Git-Release-ID konnte nicht ermittelt werden.
  exit /b 1
)

if exist "%ARCHIVE%" del /q "%ARCHIVE%"

echo [CARLY][BE] Release %RELEASE_ID% aus dem Git-Stand archivieren...
REM git archive nimmt nur versionierte Dateien auf. .env.local/.env.prod und andere
REM unversionierte Secrets koennen dadurch nicht versehentlich im Deployment landen.
git archive --format=tar.gz --output="%ARCHIVE%" HEAD || exit /b 1

echo [CARLY][BE] Release auf den Server laden...
scp -i "%SSH_KEY%" "%ARCHIVE%" %SERVER%:%REMOTE_ARCHIVE% || exit /b 1

echo [CARLY][BE] Serverseitiges Deployment starten...
ssh -t -i "%SSH_KEY%" %SERVER% "sudo %REMOTE_DEPLOY% %REMOTE_ARCHIVE% %RELEASE_ID%" || exit /b 1

if exist "%ARCHIVE%" del /q "%ARCHIVE%"

echo [CARLY][BE] Deployment erfolgreich abgeschlossen.
exit /b 0
