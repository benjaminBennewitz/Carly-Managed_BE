# apps/common/pagination.py
"""Definiert eine begrenzte Standardpagination für Listenendpunkte."""

from rest_framework.pagination import PageNumberPagination


class DefaultPagination(PageNumberPagination):
    """Verhindert unbegrenzt große API-Antworten."""

    page_size = 50
    page_size_query_param = "pageSize"
    max_page_size = 200
