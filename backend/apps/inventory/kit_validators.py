"""Keep control-panel ModelForms subject to the same kit definition contract."""

from django.core.exceptions import ValidationError
from rest_framework.exceptions import ValidationError as ApiValidationError

from apps.inventory.kit_serializers import KitDefinitionField


def validate_kit_definition(value):
    # API serializers allocate new UUIDs before persistence. Stored definitions
    # must already have them; validation must never generate a different key.
    if not isinstance(value, list) or any(not isinstance(row, dict) or set(row) != {"key", "label", "quantity"}
                                         for row in value):
        raise ValidationError("Kit components must contain only a UUID key, label and quantity.")
    try:
        validated = KitDefinitionField().run_validation(value)
    except ApiValidationError as exc:
        raise ValidationError("Enter at most 50 uniquely keyed components with names and quantities from 1 to 999.") from exc
    if any(type(row["quantity"]) is not int or not isinstance(row["label"], str)
           or row["key"] != canonical["key"] for row, canonical in zip(value, validated)):
        raise ValidationError("Store canonical UUID keys, text labels and integer quantities for kit components.")
