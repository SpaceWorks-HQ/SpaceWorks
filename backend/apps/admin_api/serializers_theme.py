from drf_spectacular.utils import OpenApiResponse, extend_schema_field
from rest_framework import serializers


@extend_schema_field({
    "type": "object",
    "additionalProperties": False,
    "description": "Public/member colours; unsafe contrast falls back to the default palette.",
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
        response={"type": "object", "additionalProperties": {}},
        description="Field validation errors, including invalid theme configuration.",
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
