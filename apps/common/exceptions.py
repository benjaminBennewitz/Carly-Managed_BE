# apps/common/exceptions.py
"""Normalisiert Fehlerantworten für das Angular-Frontend."""

from typing import Any

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework.exceptions import APIException, ErrorDetail, ValidationError
from rest_framework.response import Response
from rest_framework.views import exception_handler


class ConflictError(APIException):
    """Signalisiert einen fachlichen Konflikt mit HTTP 409."""

    status_code = 409
    default_detail = "Die Ressource wurde zwischenzeitlich geändert."
    default_code = "conflict"


class VersionConflictError(ConflictError):
    """Signalisiert eine veraltete Versionsnummer bei parallelen Änderungen."""

    default_detail = "Die gespeicherte Version ist nicht mehr aktuell."
    default_code = "version_conflict"


def _serialize_validation_detail(
    detail: Any,
) -> tuple[str, str, dict[str, Any] | None]:
    """Überführt DRF-Validierungsfehler in das vereinbarte Frontendformat."""
    if isinstance(detail, dict):
        fields: dict[str, list[dict[str, str]]] = {}
        for field, errors in detail.items():
            error_list = errors if isinstance(errors, list) else [errors]
            fields[str(field)] = [
                {
                    "code": getattr(error, "code", "invalid"),
                    "message": str(error),
                }
                for error in error_list
            ]
        return "validation_error", "Bitte prüfe die markierten Eingaben.", fields

    if isinstance(detail, list):
        first = (
            detail[0]
            if detail
            else ErrorDetail(
                "Ungültige Anfrage.",
                code="invalid",
            )
        )
        return getattr(first, "code", "invalid"), str(first), None

    return getattr(detail, "code", "invalid"), str(detail), None


def _plain_detail(detail: Any) -> Any:
    """Entfernt DRF-spezifische ErrorDetail-Objekte rekursiv."""
    if isinstance(detail, dict):
        return {str(key): _plain_detail(value) for key, value in detail.items()}
    if isinstance(detail, list):
        return [_plain_detail(value) for value in detail]
    return str(detail)


def _api_exception_payload(exc: APIException) -> dict[str, Any]:
    """Erzeugt für fachliche API-Ausnahmen einen stabilen Fehlervertrag."""
    detail = exc.detail
    if isinstance(detail, dict):
        message = str(detail.get("message", exc.default_detail))
        payload: dict[str, Any] = {
            "code": exc.default_code,
            "message": message,
        }
        details = {
            str(key): _plain_detail(value) for key, value in detail.items() if key != "message"
        }
        if details:
            payload["details"] = details
        return payload

    if isinstance(detail, list):
        first = (
            detail[0]
            if detail
            else ErrorDetail(
                str(exc.default_detail),
                code=exc.default_code,
            )
        )
        return {
            "code": getattr(first, "code", exc.default_code),
            "message": str(first),
        }

    return {
        "code": getattr(detail, "code", exc.default_code),
        "message": str(detail),
    }


def api_exception_handler(exc: Exception, context: dict[str, Any]) -> Response | None:
    """Erzeugt stabile Fehlerobjekte ohne interne Implementierungsdetails."""
    if isinstance(exc, DjangoValidationError):
        exc = ValidationError(exc.message_dict if hasattr(exc, "message_dict") else exc.messages)

    response = exception_handler(exc, context)
    if response is None:
        return None

    if isinstance(exc, ValidationError):
        code, message, fields = _serialize_validation_detail(exc.detail)
        payload: dict[str, Any] = {"code": code, "message": message}
        if fields:
            payload["fields"] = fields
        response.data = payload
        return response

    if isinstance(exc, APIException):
        response.data = _api_exception_payload(exc)
        return response

    return response
