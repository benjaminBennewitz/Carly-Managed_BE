#!/usr/bin/env bash
# scripts/deploy-carly-backend-server.sh
set -euo pipefail

ARCHIVE="${1:-/tmp/carly-managed-backend.tar.gz}"
RELEASE_ID="${2:-$(date +%Y%m%d-%H%M%S)}"

APP_ROOT="/srv/carly-managed"
APP_USER="carly"
APP_GROUP="carly"
RELEASES_DIR="$APP_ROOT/releases"
RELEASE_DIR="$RELEASES_DIR/$RELEASE_ID"
CURRENT_LINK="$APP_ROOT/current"
VENV="$APP_ROOT/.venv"
ENV_FILE="/etc/carly-managed.env"

API_SERVICE="carly-managed-api.service"
WORKER_SERVICE="carly-managed-worker.service"
BEAT_SERVICE="carly-managed-beat.service"

HEALTH_URL="http://127.0.0.1:8201/api/v1/health/"
HEALTH_HOST="cases.b2folio.de"

PREVIOUS_RELEASE=""

fail() {
  echo "[CARLY][BE][FEHLER] $*" >&2
  exit 1
}

run_as_app() {
  runuser -u "$APP_USER" -- env \
    DJANGO_ENV=production \
    CARLY_ENV_FILE="$ENV_FILE" \
    PYTHONDONTWRITEBYTECODE=1 \
    "$@"
}

rollback_current() {
  if [[ -n "$PREVIOUS_RELEASE" && -d "$PREVIOUS_RELEASE" ]]; then
    echo "[CARLY][BE] Healthcheck fehlgeschlagen. Vorherigen Code-Release wieder aktivieren..."
    ln -s "$PREVIOUS_RELEASE" "$CURRENT_LINK.rollback"
    mv -Tf "$CURRENT_LINK.rollback" "$CURRENT_LINK"
    systemctl restart "$API_SERVICE" "$WORKER_SERVICE" "$BEAT_SERVICE" || true
  fi
}

if [[ "$(id -u)" -ne 0 ]]; then
  fail "Dieses Script muss mit sudo/root ausgefuehrt werden."
fi

[[ -f "$ARCHIVE" ]] || fail "Release-Archiv nicht gefunden: $ARCHIVE"
[[ -f "$ENV_FILE" ]] || fail "Production-ENV nicht gefunden: $ENV_FILE"
id "$APP_USER" >/dev/null 2>&1 || fail "Service-User fehlt: $APP_USER"

for command in tar python3 runuser systemctl curl; do
  command -v "$command" >/dev/null 2>&1 || fail "Benoetigtes Kommando fehlt: $command"
done

if tar -tzf "$ARCHIVE" | grep -Eq '(^/|(^|/)\.\.(/|$))'; then
  fail "Unsicherer Pfad im Release-Archiv erkannt."
fi

if tar -tzf "$ARCHIVE" | grep -Eq '(^|/)\.env($|\.)'; then
  fail "ENV-Datei im Release-Archiv erkannt. Secrets duerfen nicht deployed werden."
fi

[[ ! -e "$RELEASE_DIR" ]] || fail "Release existiert bereits: $RELEASE_DIR"

mkdir -p "$RELEASE_DIR"
echo "[CARLY][BE] Release $RELEASE_ID entpacken..."
tar -xzf "$ARCHIVE" -C "$RELEASE_DIR"

[[ -f "$RELEASE_DIR/manage.py" ]] || fail "manage.py fehlt im Release."
[[ -f "$RELEASE_DIR/requirements.txt" ]] || fail "requirements.txt fehlt im Release."

chown -R "$APP_USER:$APP_GROUP" "$RELEASE_DIR"
find "$RELEASE_DIR" -type d -exec chmod 750 {} \;
find "$RELEASE_DIR" -type f -exec chmod 640 {} \;

if [[ ! -x "$VENV/bin/python" ]]; then
  echo "[CARLY][BE] Python-venv erstmalig erstellen..."
  run_as_app python3 -m venv "$VENV"
fi

echo "[CARLY][BE] Production-Abhaengigkeiten installieren..."
run_as_app "$VENV/bin/python" -m pip install \
  --disable-pip-version-check \
  -r "$RELEASE_DIR/requirements.txt"

echo "[CARLY][BE] Production-Systemcheck..."
(
  cd "$RELEASE_DIR"
  run_as_app "$VENV/bin/python" manage.py check --deploy
)

echo "[CARLY][BE] Migrationen anwenden..."
(
  cd "$RELEASE_DIR"
  run_as_app "$VENV/bin/python" manage.py migrate --noinput
)

echo "[CARLY][BE] Static-Dateien sammeln..."
REMINDER="Static wird bewusst nicht mit --clear gesammelt, damit ein Code-Rollback alte Hash-Dateien weiterhin findet."
echo "[CARLY][BE] $REMINDER"
(
  cd "$RELEASE_DIR"
  run_as_app "$VENV/bin/python" manage.py collectstatic --noinput
)

if [[ -f "$RELEASE_DIR/apps/demo/management/commands/provision_demo_user.py" ]]; then
  echo "[CARLY][BE] Oeffentlichen Demo-User und Seed sicherstellen..."
  (
    cd "$RELEASE_DIR"
    run_as_app "$VENV/bin/python" manage.py provision_demo_user
  )
fi

if [[ -L "$CURRENT_LINK" ]]; then
  PREVIOUS_RELEASE="$(readlink -f "$CURRENT_LINK" || true)"
fi

echo "[CARLY][BE] Release atomar aktivieren..."
ln -s "$RELEASE_DIR" "$CURRENT_LINK.next"
mv -Tf "$CURRENT_LINK.next" "$CURRENT_LINK"

for unit in \
  carly-managed-api.service \
  carly-managed-worker.service \
  carly-managed-beat.service
do
  [[ -f "$RELEASE_DIR/deploy/systemd/$unit" ]] || fail "systemd-Unit fehlt im Release: $unit"
  install -o root -g root -m 0644 \
    "$RELEASE_DIR/deploy/systemd/$unit" \
    "/etc/systemd/system/$unit"
done

systemctl daemon-reload
systemctl enable "$API_SERVICE" "$WORKER_SERVICE" "$BEAT_SERVICE" >/dev/null

echo "[CARLY][BE] Services neu starten..."
if ! systemctl restart "$API_SERVICE" "$WORKER_SERVICE" "$BEAT_SERVICE"; then
  rollback_current
  fail "Mindestens ein Carly-Service konnte nicht gestartet werden."
fi

echo "[CARLY][BE] Readiness-Healthcheck..."
HEALTH_OK=0
for attempt in $(seq 1 20); do
  if curl -fsS \
    --max-time 5 \
    -H "Host: $HEALTH_HOST" \
    -H "X-Forwarded-Proto: https" \
    "$HEALTH_URL" | grep -q '"status"[[:space:]]*:[[:space:]]*"ok"'; then
    HEALTH_OK=1
    break
  fi
  sleep 1
done

if [[ "$HEALTH_OK" -ne 1 ]]; then
  journalctl -u "$API_SERVICE" -n 80 --no-pager || true
  rollback_current
  fail "API-Healthcheck blieb erfolglos."
fi

echo "[CARLY][BE] Services pruefen..."
systemctl --no-pager --full status "$API_SERVICE" | sed -n '1,12p'
systemctl --no-pager --full status "$WORKER_SERVICE" | sed -n '1,12p'
systemctl --no-pager --full status "$BEAT_SERVICE" | sed -n '1,12p'

rm -f "$ARCHIVE"

echo "[CARLY][BE] Alte Releases auf die letzten 5 begrenzen..."
mapfile -t OLD_RELEASES < <(find "$RELEASES_DIR" -mindepth 1 -maxdepth 1 -type d -printf '%T@ %p\n' \
  | sort -nr \
  | awk 'NR > 5 {sub(/^[^ ]+ /, ""); print}')

for old_release in "${OLD_RELEASES[@]:-}"; do
  [[ -n "$old_release" ]] || continue
  if [[ "$(readlink -f "$CURRENT_LINK")" != "$old_release" ]]; then
    rm -rf "$old_release"
  fi
done

echo "[CARLY][BE] Deployment erfolgreich: $RELEASE_ID"
