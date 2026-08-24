from rest_framework import serializers

from apps.makerspaces.limits_core import BOOLEAN_LIMIT_KEYS, KNOWN_LIMIT_KEYS


def validate_resource_limit_overrides(value) -> dict:
    if not isinstance(value, dict):
        raise serializers.ValidationError("Resource limit overrides must be an object.")

    validated = {}
    for key, limit in value.items():
        if key not in KNOWN_LIMIT_KEYS:
            raise serializers.ValidationError(f"Unknown resource limit key: {key}.")
        if key in BOOLEAN_LIMIT_KEYS:
            if not isinstance(limit, bool):
                raise serializers.ValidationError(
                    {key: "This resource limit must be true or false."}
                )
        elif limit is not None and (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or limit < -1
        ):
            raise serializers.ValidationError(
                {key: "Use a non-negative integer, -1, or null."}
            )
        validated[key] = limit
    return validated
