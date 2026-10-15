"""Reject misspelled settings instead of DRF's default unknown-field omission."""
from rest_framework.exceptions import ValidationError


def validate_settings(serializer):
    writable = {key for key, field in serializer.fields.items() if not field.read_only}
    unknown = set(serializer.initial_data) - writable
    if unknown:
        raise ValidationError({key: "Unknown or read-only setting." for key in sorted(unknown)})
    serializer.is_valid(raise_exception=True)
