<!-- docs/PRODUCTION_DEPLOYMENT.md -->
# Produktionsdeployment

## Zielarchitektur

Ein Angular-Build wird einmal erzeugt und unverändert in zwei getrennte KeyHelp-Webroots verteilt:

- `https://cases.b2folio.de`
- `https://cases.design-code-repeat.de`

Beide Hosts verwenden Same-Origin-Routen und proxien `/api/` sowie `/ws/` auf denselben projektisolierten Daphne-Dienst. Es gibt keinen Redirect zwischen den Domains. Sitzungs- und CSRF-Cookies bleiben hostgebunden.

Das Backend läuft getrennt von anderen Projekten unter `/srv/carly-managed/`. Eine zentrale PostgreSQL-Instanz darf mehrere Projekte versorgen, aber Carly erhält eine eigene Datenbank und einen eigenen DB-Login. Redis wird ebenfalls geteilt, Carly nutzt jedoch einen eigenen ACL-Benutzer und die logischen Datenbanken 10, 11 und 12.

## Persistente Pfade

```text
/srv/carly-managed/
├── current -> releases/<release>/
├── releases/
├── .venv/
└── shared/
    ├── static/
    ├── media/
    └── celery/
```

`MEDIA_ROOT` darf niemals im austauschbaren Release-Verzeichnis liegen. Benutzer-Uploads werden ausschließlich über autorisierte Django-Endpunkte ausgeliefert und nicht als öffentliches Apache-`Alias /media/` freigegeben.

## Static Files

Django 5.2 verwendet `STORAGES` mit `CompressedManifestStaticFilesStorage`. Vor jedem Backend-Restart:

```bash
DJANGO_ENV=production CARLY_ENV_FILE=/etc/carly-managed.env \
  /srv/carly-managed/.venv/bin/python manage.py collectstatic --noinput --clear
```

Danach muss `staticfiles.json` unter `/srv/carly-managed/shared/static/` existieren. `collectstatic` wird als Deployment-Schritt ausgeführt und nicht beim Start jedes Workers.

## Prozesse

Produktiv werden drei systemd-Dienste benötigt:

1. Daphne für HTTP + WebSocket
2. Celery Worker
3. Celery Beat

PostgreSQL und Redis laufen als gemeinsame Infrastruktur, jedoch mit projektbezogener Zugriffstrennung.

## systemd-Vorlagen

Die versionierten Units liegen unter `deploy/systemd/`:

- `carly-managed-api.service`
- `carly-managed-worker.service`
- `carly-managed-beat.service`

Sie verwenden den dedizierten Systembenutzer `carly-managed`, den stabilen Symlink
`/srv/carly-managed/current` und schreiben ausschließlich in `/srv/carly-managed/shared/`.
Vor der Aktivierung werden sie nach `/etc/systemd/system/` kopiert und anschließend mit
`systemctl daemon-reload` eingelesen.

Die Apache-Vorlage für die benutzerdefinierten HTTPS-Anweisungen liegt unter
`deploy/apache/carly-managed-proxy.conf.example`. Derselbe Proxyblock wird auf beiden
öffentlichen Hosts verwendet.

## Apache / KeyHelp

Für beide HTTPS-Hosts gelten dieselben Proxyregeln:

```apache
ProxyPreserveHost On

ProxyPass /api/ http://127.0.0.1:8201/api/
ProxyPassReverse /api/ http://127.0.0.1:8201/api/

ProxyPass /ws/ ws://127.0.0.1:8201/ws/
ProxyPassReverse /ws/ ws://127.0.0.1:8201/ws/

RequestHeader set X-Forwarded-Proto "https"
RequestHeader set X-Forwarded-Port "443"
```

Der Frontend-Build besitzt zusätzlich einen Angular-SPA-Fallback in `.htaccess`. `/api` und `/ws` werden davon ausdrücklich ausgeschlossen.

## Dual-Domain-E-Mails

Verifizierungs-, Reset- und Einladungslinks werden aus dem validierten Request-Host erzeugt. Für jeden produktiven Frontend-Host muss `DJANGO_EMAIL_FROM_BY_HOST` eine passende Absenderidentität enthalten. So verweist eine über DCR ausgelöste E-Mail nicht auf B²Folio und umgekehrt.
