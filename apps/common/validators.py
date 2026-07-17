# apps/common/validators.py
"""Validiert häufig verwendete Text-, Farb- und Dateieingaben."""

import re
from pathlib import Path

import filetype
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import UploadedFile

CONTROL_CHARACTERS = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]")
HEX_COLOR = re.compile(r"^#[0-9A-Fa-f]{6}$")
SAFE_ICON = re.compile(r"^[a-z0-9_]{1,50}$")
ALLOWED_UPLOADS = {
    ".pdf": {"application/pdf"},
    ".png": {"image/png"},
    ".jpg": {"image/jpeg"},
    ".jpeg": {"image/jpeg"},
    ".webp": {"image/webp"},
    ".txt": {"text/plain"},
    ".csv": {"text/csv", "text/plain"},
    ".docx": {"application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
    ".xlsx": {"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"},
}


def reject_control_characters(value: str) -> None:
    """Verhindert unsichtbare Steuerzeichen in persistierten Texten."""
    if CONTROL_CHARACTERS.search(value):
        raise ValidationError("Unsichtbare Steuerzeichen sind nicht erlaubt.", code="control_chars")


def validate_hex_color(value: str) -> None:
    """Erlaubt ausschließlich sechsstellige hexadezimale Farben."""
    if not HEX_COLOR.fullmatch(value):
        raise ValidationError("Bitte gib eine gültige Hex-Farbe an.", code="invalid_color")


def validate_material_icon(value: str) -> None:
    """Begrenzt Icons auf sichere lokale Material-Symbol-Bezeichner."""
    if not SAFE_ICON.fullmatch(value):
        raise ValidationError("Das Icon enthält unzulässige Zeichen.", code="invalid_icon")


def validate_upload(upload: UploadedFile) -> None:
    """Prüft Größe, Dateiendung und erkannten Inhalt eines Uploads."""
    if upload.size > settings.FILE_UPLOAD_MAX_BYTES:
        raise ValidationError("Die Datei überschreitet die maximale Größe.", code="file_too_large")

    extension = Path(upload.name).suffix.lower()
    allowed_mime_types = ALLOWED_UPLOADS.get(extension)
    if not allowed_mime_types:
        raise ValidationError("Dieser Dateityp ist nicht erlaubt.", code="file_type_not_allowed")

    header = upload.read(261)
    upload.seek(0)
    guessed = filetype.guess(header)
    detected_mime = guessed.mime if guessed else upload.content_type
    if detected_mime not in allowed_mime_types:
        raise ValidationError(
            "Dateiendung und Dateiinhalt stimmen nicht überein.", code="mime_mismatch"
        )
