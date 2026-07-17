<!-- docs/SECURITY.md -->
# Sicherheitskonzept

## Authentifizierung

- Serverseitige Django-Sitzungen in `HttpOnly`-Cookies
- CSRF-Schutz für alle zustandsändernden Session-Requests
- Argon2 als bevorzugter Passwort-Hasher
- Generische Login- und Recovery-Antworten gegen Benutzer-Ermittlung
- IP- und nutzerbezogenes Throttling
- Zeitliche Kontosperre nach wiederholten Fehlversuchen
- Rotierende Session-ID nach erfolgreicher Anmeldung
- Zeitlich begrenzte, gehashte und einmalig nutzbare Verifizierungs- und Reset-Tokens

## Eingaben

- Serializer- und Model-Validierung
- Längenbegrenzungen und Zurückweisung von Steuerzeichen
- Serverseitige Passwortvalidierung
- Strikte Enum-Felder statt frei interpretierter Statuswerte
- Upload-Limit, erlaubte MIME-Typen, Signaturprüfung und bereinigte Dateinamen
- Keine HTML-Ausgabe ungefilterter Nutzereingaben durch die API

## Autorisierung

- Standardmäßig ist jeder API-Endpunkt authentifizierungspflichtig
- Ressourcen werden per Queryset auf erlaubte Workspaces eingeschränkt
- Objektbezogene Schreibrechte werden zusätzlich in Services und Views geprüft
- WebSocket-Verbindungen prüfen dieselbe Session und Board-Berechtigung
- Private Anhänge werden niemals direkt durch den Webserver veröffentlicht


## Demo-Daten

- API-Reset nur bei aktivem Feature-Flag und authentifiziertem Staff-Konto
- produktiv zusätzliches explizites Freigabe-Flag erforderlich
- Rate-Limit von zwei Resets pro Minute
- transaktionaler Ersatz ausschließlich des benannten Demo-Workspaces des Owners
- keine Löschung anderer Workspaces oder Benutzerkonten
- geplante Resets wählen niemals zufällig aus mehreren Staff-Konten

## Produktion

- HTTPS-Weiterleitung, HSTS, sichere Cookies, `X-Frame-Options: DENY` und MIME-Sniffing-Schutz
- CORS- und CSRF-Ursprünge ausschließlich über Umgebungsvariablen
- Secrets ausschließlich aus der Umgebung
- PostgreSQL, Redis und SMTP nicht öffentlich exponieren
- Reverse Proxy muss `X-Forwarded-Proto` korrekt setzen
- Regelmäßige Abhängigkeitsprüfungen mit `pip-audit`

## Noch infrastrukturell zu ergänzen

Ein Malware-Scanner für hochgeladene Dateien, ein produktiver E-Mail-Dienst, Backups, Monitoring, Secret-Rotation und gegebenenfalls Object Storage sind Deployment-Aufgaben und nicht im Quellcode simulierbar.
