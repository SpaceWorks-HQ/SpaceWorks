from drf_spectacular.utils import OpenApiResponse, extend_schema_field
from rest_framework import serializers


@extend_schema_field({
    "type": "object",
    "additionalProperties": False,
    "description": (
        "Public/member secondary colours. Foreground, hover/pressed states and light/dark "
        "link ink are derived automatically. Rejects palettes below 4.5:1 text or 3:1 "
        "component contrast in either mode (including 80% counter text and tinted surfaces). "
        "Blank colours use the product palette. Staff chrome and status colours stay fixed."
    ),
    "properties": {
        "mode": {"type": "string", "enum": ["system", "light", "dark"]},
        "primary_color": {"type": "string", "pattern": r"^$|^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$"},
        "accent_color": {"type": "string", "pattern": r"^$|^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$"},
        "logo_url": {"type": "string", "maxLength": 2048},
    },
})
class ThemeConfigField(serializers.JSONField):
    """Document the closed JSON object while retaining existing partial blobs."""


MAKERSPACE_WRITE_ERRORS = {
    400: OpenApiResponse(
        response={
            "type": "object",
            "additionalProperties": {},
            "properties": {
                "theme_config": {
                    "oneOf": [
                        {"type": "array", "items": {"type": "string"}},
                        {
                            "type": "object",
                            "required": ["code", "messages"],
                            "properties": {
                                "code": {"type": "string", "enum": ["theme_contrast"]},
                                "messages": {"type": "array", "items": {"type": "string"}},
                            },
                        },
                    ],
                },
            },
        },
        description=(
            "Field validation errors. Contrast errors have theme_config: "
            "{code: 'theme_contrast', messages: string[]} with mode, failing pair, "
            "measured ratio and required ratio."
        ),
    ),
    401: OpenApiResponse(
        response={"type": "object", "properties": {"detail": {"type": "string"}}},
        description="Authentication required.",
    ),
    403: OpenApiResponse(
        response={"type": "object", "properties": {"detail": {"type": "string"}}},
        description="Active staff with the required makerspace action must authorize the write.",
    ),
}
