"""Canonical machine metering units and type-config validation."""

from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db import models


class MeteringUnit(models.TextChoices):
    MINUTES = "minutes", "Minutes"
    WEIGHT = "weight", "Weight"
    VOLUME = "volume", "Volume"
    LENGTH = "length", "Length"
    COUNT = "count", "Count"


class ConsumablePoolUnit(models.TextChoices):
    GRAMS = "grams", "Grams"
    MILLILITERS = "milliliters", "Milliliters"
    MILLIMETERS = "millimeters", "Millimeters"
    COUNT = "count", "Count"


_POOL_UNITS = {
    MeteringUnit.WEIGHT: ConsumablePoolUnit.GRAMS,
    MeteringUnit.VOLUME: ConsumablePoolUnit.MILLILITERS,
    MeteringUnit.LENGTH: ConsumablePoolUnit.MILLIMETERS,
    MeteringUnit.COUNT: ConsumablePoolUnit.COUNT,
}
_METERING_UNITS = {value: key for key, value in _POOL_UNITS.items()}


def pool_unit_for_metering(unit):
    return _POOL_UNITS.get(unit)


def metering_unit_for_pool(unit):
    return _METERING_UNITS.get(unit)


def validate_type_config(config, *, is_custom=False):
    """Validate structural type config; pricing never belongs in this JSON."""
    if not isinstance(config, dict):
        raise ValidationError("Machine type capability_config must be an object.")
    forbidden = {"rate_per_unit", "flat_fee", "currency", "payment_enabled", "payment_authorized", "authorization"}
    present = forbidden & set(config)
    if present:
        raise ValidationError(f"capability_config cannot contain {sorted(present)[0]}.")
    if is_custom:
        missing = {"metering_unit", "requires_booking"} - set(config)
        if missing:
            raise ValidationError(f"Custom machine types require {sorted(missing)[0]}.")
    if "metering_unit" in config and config["metering_unit"] not in MeteringUnit.values:
        raise ValidationError("metering_unit must be a supported metering unit.")
    if "requires_booking" in config and type(config["requires_booking"]) is not bool:
        raise ValidationError("requires_booking must be true or false.")
    if is_custom:
        for key in ("accepted_materials", "accepted_colours"):
            if key not in config:
                continue
            value = config[key]
            if not isinstance(value, list) or not value or any(not isinstance(item, str) or not item.strip() for item in value):
                raise ValidationError(f"Machine type {key} must be a non-empty list of names.")
            if len({item.casefold() for item in value}) != len(value):
                raise ValidationError(f"Machine type {key} cannot contain duplicates.")
