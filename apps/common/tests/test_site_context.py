# apps/common/tests/test_site_context.py
"""Prüft die hostabhängige öffentliche Site-Identität."""

from django.test import RequestFactory, SimpleTestCase, override_settings

from apps.common.site_context import resolve_site_context


@override_settings(
    ALLOWED_HOSTS=["cases.b2folio.de", "cases.design-code-repeat.de"],
    FRONTEND_URL="https://cases.b2folio.de",
    FRONTEND_URLS=[
        "https://cases.b2folio.de",
        "https://cases.design-code-repeat.de",
    ],
    DEFAULT_FROM_EMAIL="Carly Managed <kontakt@b2folio.de>",
    EMAIL_FROM_BY_HOST={
        "cases.b2folio.de": "Carly Managed <kontakt@b2folio.de>",
        "cases.design-code-repeat.de": ("Carly Managed <kontakt@design-code-repeat.de>"),
    },
)
class SiteContextTests(SimpleTestCase):
    """Verhindert domainübergreifende Links und Absenderidentitäten."""

    def test_request_host_selects_matching_site_context(self) -> None:
        """Verwendet für DCR weder B²Folio-Link noch B²Folio-Absender."""
        request = RequestFactory().get(
            "/api/v1/auth/csrf/",
            secure=True,
            HTTP_HOST="cases.design-code-repeat.de",
        )

        context = resolve_site_context(request)

        self.assertEqual(context.frontend_url, "https://cases.design-code-repeat.de")
        self.assertEqual(
            context.from_email,
            "Carly Managed <kontakt@design-code-repeat.de>",
        )

    def test_default_https_port_keeps_matching_host(self) -> None:
        """Ignoriert einen expliziten Standardport bei der Hostzuordnung."""
        request = RequestFactory().get(
            "/api/v1/auth/csrf/",
            secure=True,
            HTTP_HOST="cases.b2folio.de",
        )
        request.META["HTTP_HOST"] = "cases.b2folio.de:443"

        context = resolve_site_context(request)

        self.assertEqual(context.frontend_url, "https://cases.b2folio.de")
        self.assertEqual(context.from_email, "Carly Managed <kontakt@b2folio.de>")
