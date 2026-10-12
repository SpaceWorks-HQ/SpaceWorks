"""Closed, CSS-safe tenant theme configuration shared by API and control forms."""

import re

from django.core.exceptions import ValidationError
from django.core.validators import URLValidator

from apps.makerspaces.theme_contrast import contrast_failures


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
    failures = contrast_failures(value)
    if failures:
        # Django keeps codes on individual errors, not on a containing error list.
        # DRF uses these codes to return the documented contrast error object.
        raise ValidationError([
            ValidationError(
                f"{item['mode']}: {item['pair']} is {item['ratio']:.2f}:1; "
                f"requires {item['minimum']}:1. Choose a lighter or darker primary colour.",
                code="theme_contrast",
            ) for item in failures
        ])
    return value


def public_theme_config(value):
    """Fallback colours without dropping a valid legacy logo or theme mode."""
    from apps.makerspaces.models import default_theme_config

    theme = default_theme_config()
    if not isinstance(value, dict):
        return theme
    # Preserve independently valid presentation keys even if restored colours
    # are unsafe. Validation here never writes back into the tenant's row.
    for key in ("mode", "logo_url"):
        if key not in value:
            continue
        try:
            validate_theme_config({key: value[key]})
        except ValidationError:
            continue
        theme[key] = value[key]
    palette = {key: value[key] for key in ("primary_color", "accent_color") if key in value}
    try:
        validate_theme_config(palette)
    except ValidationError:
        pass
    else:
        theme.update(palette)
    return theme
