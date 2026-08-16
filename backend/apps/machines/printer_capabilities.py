"""The validated capability pack for the built-in 3D-printer machine type."""

from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError


PRINTER_SLUG = "3d_printer"
PRINTER_CONFIG = {
    "schema": "3d-printer-v1",
    "service_payload_schema": "printer-v1",
    "machine_payload_schema": "printer-machine-v1",
    "accepted_materials": ["PLA", "PETG", "TPU"],
    "accepted_colours": ["Black", "Blue", "Green", "Red", "White", "Gray"],
    "metering_unit": "weight",
    "pooled_service_queue": True,
    "typed_consumable_pools": True,
    "service_file_policy": {"name": "printer", "version": 1},
    "printer_hours": True,
    "run_sheet_required": True,
}

_REQUIRED_CONFIG_KEYS = frozenset(PRINTER_CONFIG)


def is_printer_type(machine_type):
    return machine_type is not None and machine_type.makerspace_id is None and machine_type.slug == PRINTER_SLUG


def resolve_global_printer_type():
    """Return the built-in printer type, or ``None`` when it is not installed."""
    # MachineType imports this module for its validators, so resolve the model lazily.
    from apps.machines.models import MachineType

    return MachineType.objects.filter(
        makerspace__isnull=True,
        slug=PRINTER_SLUG,
    ).first()


def validate_printer_config(machine_type, config):
    """Validate the global printer pack while leaving ordinary type packs alone."""
    if not is_printer_type(machine_type):
        return
    if not isinstance(config, dict) or set(config) != _REQUIRED_CONFIG_KEYS:
        raise ValidationError("The 3D-printer capability contract has an invalid shape.")
    for key in ("schema", "service_payload_schema", "machine_payload_schema"):
        if config[key] != PRINTER_CONFIG[key]:
            raise ValidationError(f"The 3D-printer {key} is protected.")
    for key in ("pooled_service_queue", "typed_consumable_pools", "printer_hours", "run_sheet_required"):
        if config[key] is not True:
            raise ValidationError(f"The 3D-printer {key} capability is required.")
    if config["service_file_policy"] != PRINTER_CONFIG["service_file_policy"]:
        raise ValidationError("The 3D-printer file policy is protected.")
    for key in ("accepted_materials", "accepted_colours"):
        value = config[key]
        if not isinstance(value, list) or not value or any(not isinstance(item, str) or not item.strip() for item in value):
            raise ValidationError(f"The 3D-printer {key} must be a non-empty list of names.")
        if len({item.casefold() for item in value}) != len(value):
            raise ValidationError(f"The 3D-printer {key} cannot contain duplicates.")


def validate_machine_payload(machine_type, payload):
    if not is_printer_type(machine_type):
        return
    if not isinstance(payload, dict) or set(payload) != {"model"} or not isinstance(payload.get("model"), str) or not payload["model"].strip():
        raise ValidationError({"type_payload": "3D-printer machines require exactly one non-empty model."})


def validate_service_payload(machine_type, payload):
    if not isinstance(payload, dict):
        raise ValidationError("capability_payload must be an object.")
    if not is_printer_type(machine_type):
        if payload:
            raise ValidationError("This machine type does not accept a capability payload.")
        return
    allowed = {"requested_material", "requested_color", "quantity", "preferred_settings", "estimated_grams", "project_brief", "requested_consumable_pool", "no_filament_preference"}
    if set(payload) - allowed:
        raise ValidationError("capability_payload contains unsupported printer fields.")
    for key, config_key in (("requested_material", "accepted_materials"), ("requested_color", "accepted_colours")):
        value = payload.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ValidationError(f"Printer {key} is required.")
        if value.casefold() not in {item.casefold() for item in machine_type.capability_config[config_key]}:
            raise ValidationError(f"Printer {key} is not accepted by this machine type.")
    quantity = payload.get("quantity")
    if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity <= 0:
        raise ValidationError("Printer quantity must be a positive whole number.")
    if "estimated_grams" in payload:
        _positive_decimal(payload["estimated_grams"], "estimated_grams")
    if "requested_consumable_pool" in payload and (isinstance(payload["requested_consumable_pool"], bool) or not isinstance(payload["requested_consumable_pool"], int) or payload["requested_consumable_pool"] <= 0):
        raise ValidationError("requested_consumable_pool must be a positive identifier.")
    if "no_filament_preference" in payload and not isinstance(payload["no_filament_preference"], bool):
        raise ValidationError("no_filament_preference must be true or false.")
    if "preferred_settings" in payload and not isinstance(payload["preferred_settings"], dict):
        raise ValidationError("preferred_settings must be an object.")
    if "project_brief" in payload and not isinstance(payload["project_brief"], str):
        raise ValidationError("project_brief must be text.")


def validate_pool(machine, pool, payload=None):
    if not is_printer_type(machine.machine_type):
        return
    config = machine.machine_type.capability_config
    material = pool.material.casefold()
    color = pool.color.casefold()
    if material not in {item.casefold() for item in config["accepted_materials"]}:
        raise ValidationError({"consumable_pool": "Pool material is not accepted by this printer type."})
    if color not in {item.casefold() for item in config["accepted_colours"]}:
        raise ValidationError({"consumable_pool": "Pool colour is not accepted by this printer type."})
    if payload and not payload.get("no_filament_preference", False):
        if material != payload["requested_material"].casefold() or color != payload["requested_color"].casefold():
            raise ValidationError({"consumable_pool": "Pool material and colour must match the print request."})


def _positive_decimal(value, name):
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValidationError(f"Printer {name} must be numeric.") from exc
    if not parsed.is_finite() or parsed <= 0:
        raise ValidationError(f"Printer {name} must be greater than zero.")
    return parsed
