# apps/common/site_context.py
"""Löst hostabhängige Frontend- und Mailidentitäten sicher auf."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit

from django.conf import settings
from django.http import HttpRequest


@dataclass(frozen=True, slots=True)
class SiteContext:
    """Bündelt die öffentliche Origin und Absenderidentität eines Frontend-Hosts."""

    frontend_url: str
    from_email: str


def resolve_site_context(request: HttpRequest) -> SiteContext:
    """Verwendet nur konfigurierte Frontend-Origins und niemals freie Host-Werte."""
    request_host = (urlsplit(f"//{request.get_host()}").hostname or "").lower()
    configured_urls = tuple(settings.FRONTEND_URLS)
    frontend_url = next(
        (
            url
            for url in configured_urls
            if urlsplit(url).scheme == request.scheme
            and (urlsplit(url).hostname or "").lower() == request_host
        ),
        settings.FRONTEND_URL,
    )
    host = (urlsplit(frontend_url).hostname or "").lower()
    from_email = settings.EMAIL_FROM_BY_HOST.get(host, settings.DEFAULT_FROM_EMAIL)
    return SiteContext(frontend_url=frontend_url, from_email=from_email)
