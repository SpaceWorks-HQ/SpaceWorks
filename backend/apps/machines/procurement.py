"""Kernel destinations for received printing procurement items."""

from decimal import Decimal

from rest_framework.exceptions import ValidationError

from apps.machines.models import Machine, MachineConsumablePool, MachineType
from apps.machines.printer_capabilities import PRINTER_SLUG


def move_received_printing(makerspace, actor, *, target, data, machine_type=None):
    if target == "printer":
        return _create_printer(makerspace, actor, data, machine_type)
    if target == "spool":
        return _create_pool(makerspace, actor, data, machine_type)
    raise ValidationError({"target": "Use spool or printer."})


def _create_printer(makerspace, actor, data, machine_type):
    name = str(data.get("name") or "").strip()
    model = str(data.get("model") or "").strip()
    if not name:
        raise ValidationError({"name": "This field is required."})
    if not model:
        raise ValidationError({"model": "This field is required."})
    printer_type = MachineType.objects.get(makerspace__isnull=True, slug=PRINTER_SLUG)
    if machine_type is not None and machine_type.pk != printer_type.pk:
        raise ValidationError(
            {"machine_type": "This item cannot create a machine of another type."}
        )
    status = {"maintenance": Machine.Status.MAINTENANCE, "offline": Machine.Status.OFFLINE}.get(data.get("status"), Machine.Status.IDLE)
    return Machine.objects.create(makerspace=makerspace, machine_type=printer_type, name=name, notes=str(data.get("notes") or ""), status=status, is_active=data.get("is_active", True), type_payload={"model": model}, created_by=actor)


def _create_pool(makerspace, actor, data, machine_type):
    material = str(data.get("material") or "").strip()
    if not material:
        raise ValidationError({"material": "This field is required."})
    initial = data.get("initial_weight_grams")
    remaining = data.get("remaining_weight_grams", initial)
    if initial is None:
        raise ValidationError({"initial_weight_grams": "This field is required."})
    initial = Decimal(str(initial))
    if initial < 0:
        raise ValidationError({"initial_weight_grams": "Must be zero or greater."})
    if remaining is None:
        raise ValidationError({"remaining_weight_grams": "Remaining weight cannot exceed initial weight."})
    remaining = Decimal(str(remaining))
    if remaining < 0:
        raise ValidationError({"remaining_weight_grams": "Must be zero or greater."})
    if remaining > initial:
        raise ValidationError({"remaining_weight_grams": "Remaining weight cannot exceed initial weight."})
    machine = None
    if data.get("printer") is not None:
        machine = Machine.objects.filter(pk=data["printer"], makerspace=makerspace, machine_type__slug=PRINTER_SLUG).first()
        if machine is None:
            raise ValidationError({"printer": "Printer must belong to the same makerspace."})
        if machine_type is not None and machine.machine_type_id != machine_type.pk:
            raise ValidationError(
                {"machine_type": "This item cannot create a pool for another machine type."}
            )
    pool = MachineConsumablePool.objects.create(
        makerspace=makerspace,
        machine=machine,
        machine_type=machine_type if machine is None else None,
        material=material,
        color=str(data.get("color") or "").strip(),
        brand=str(data.get("brand") or "").strip(),
        lot_code=str(data.get("lot_code") or "").strip(),
        initial_grams=initial,
        remaining_grams=remaining,
        low_threshold_grams=makerspace.filament_low_stock_threshold_grams or None,
        is_active=data.get("is_active", True),
        opened_at=data.get("opened_at"),
        created_by=actor,
    )
    from apps.machines.low_stock import maybe_flag_low_stock
    maybe_flag_low_stock(actor, pool)
    return pool
