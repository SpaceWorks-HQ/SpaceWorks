"""Closed, CSS-safe tenant theme configuration shared by API and control forms."""

import re

from django.core.exceptions import ValidationError
from django.core.validators import URLValidator


THEME_KEYS = frozenset({"mode", "primary_color", "accent_color", "logo_url"})
HEX_COLOR = re.compile(r"#[0-9a-fA-F]{3}(?:[0-9a-fA-F]{3})?\Z")


def validate_theme_config(value):
    if not isinstance(value, dict):
        raise ValidationError("Theme configuration must be an object.")
    if value.keys() - THEME_KEYS:
        raise ValidationError("Theme configuration contains unsupported keys.")
    for key, item in value.items():
        if not isinstance(item, str):
            raise ValidationError(f"{key} must be a string.")
        if key == "mode" and item not in {"system", "light", "dark"}:
            raise ValidationError("Theme mode must be system, light or dark.")
        if key in {"primary_color", "accent_color"} and item and not HEX_COLOR.fullmatch(item):
            raise ValidationError(f"{key} must be a #RGB or #RRGGBB colour, or blank.")
        if key == "logo_url" and item:
            if len(item) > 2048:
                raise ValidationError("Logo URL must be at most 2048 characters.")
            URLValidator(schemes=["https", "http"])(item)
    # Contrast depends on the rendered light/dark text and surfaces. The client
    # checks those actual tokens and falls back per colour; do not reject brands
    # that are usable in only one mode at the storage boundary.
    return value
