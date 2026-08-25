"""Compatibility wrappers that add generic metering to the pooled ledger."""

from decimal import Decimal, InvalidOperation

from django.db import transaction
from rest_framework.exceptions import ValidationError

from apps.audit import services as audit
from apps.machines.consumable_scope import pool_serves_machine
from apps.machines.metering import MeteringUnit, metering_unit_for_pool, pool_unit_for_metering
from apps.machines.models import MachineConsumableAdjustment, MachineServiceRequest


def _quantity(value, field):
    try:
        parsed = Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValidationError({field: "Enter a valid quantity."}) from exc
    if not parsed.is_finite() or parsed < 0:
        raise ValidationError({field: "Enter a non-negative quantity."})
    return parsed


def _unit(request, machine):
    configured = (machine.machine_type.capability_config or {}).get("metering_unit")
    unit = request.metering_unit or configured or MeteringUnit.WEIGHT
    if unit not in MeteringUnit.values:
        raise ValidationError({"metering_unit": "Unsupported metering unit."})
    return unit


def _apply(pool, actor, *, kind, delta, service_request=None, usage_entry=None, reason="", metering_unit=None):
    delta = Decimal(delta).quantize(Decimal("0.01"))
    after = pool.remaining_grams + delta
    if after < 0:
        unit = "grams" if pool.unit == "grams" else pool.unit
        raise ValidationError({"grams": f"Only {pool.remaining_grams} {unit} remain."})
    if after > pool.initial_grams:
        unit = "grams" if pool.unit == "grams" else pool.unit
        raise ValidationError({"grams": f"Adjustment would exceed initial {unit}."})
    unit = metering_unit or metering_unit_for_pool(pool.unit) or MeteringUnit.WEIGHT
    row = MachineConsumableAdjustment.objects.create(
        consumable_pool=pool, makerspace=pool.makerspace, kind=kind, quantity_delta=delta,
        metering_unit=unit, consumed_quantity=delta, service_request=service_request,
        usage_entry=usage_entry, reason=str(reason).strip(), created_by=actor,
    )
    pool.remaining_grams = after
    pool.save(update_fields=["remaining_grams", "updated_at"])
    audit.record(actor, f"machine_consumable_pool.{kind}", makerspace=pool.makerspace, target=row,
                 meta={"pool_id": pool.pk, "adjustment_id": row.pk, "quantity_delta": str(delta),
                       "remaining_grams": str(after), "request_id": getattr(service_request, "pk", None),
                       "usage_entry_id": getattr(usage_entry, "pk", None)})
    if delta < 0:
        from apps.machines.low_stock import maybe_flag_low_stock
        maybe_flag_low_stock(actor, pool)
    return row


def reserve_for_request(legacy, service_request, actor, *, pool, planned_grams=None, planned_quantity=None, machine):
    if planned_quantity is None:
        row = legacy(service_request, actor, pool=pool, planned_grams=planned_grams, machine=machine)
        row.metering_unit = MeteringUnit.WEIGHT
        row.planned_quantity = row.planned_grams
        row.reserved_quantity = row.reserved_grams
        row.save(update_fields=["metering_unit", "planned_quantity", "reserved_quantity", "updated_at"])
        return row
    with transaction.atomic():
        request = MachineServiceRequest.objects.select_for_update(of=("self",)).get(pk=service_request.pk)
        locked = pool.__class__.objects.select_for_update(of=("self",)).select_related("makerspace", "machine").get(pk=pool.pk)
        unit = _unit(request, machine)
        quantity = _quantity(planned_quantity, "planned_quantity")
        if not quantity:
            raise ValidationError({"planned_quantity": "Planned quantity must be greater than zero."})
        expected_pool_unit = pool_unit_for_metering(unit)
        if expected_pool_unit is None or locked.unit != expected_pool_unit:
            raise ValidationError({"consumable_pool": "Consumable pool unit is incompatible with this metering unit."})
        if not locked.is_active:
            raise ValidationError({"consumable_pool": "Consumable pool is retired."})
        # Keep the request-tenant assertion the scope helper does not make: it binds the pool to the
        # MACHINE's makerspace, while the check it replaced bound it to the REQUEST's.
        if locked.makerspace_id != request.makerspace_id or not pool_serves_machine(locked, machine):
            raise ValidationError({"consumable_pool": "Consumable pool is incompatible with this machine service request."})
        from apps.machines.printer_capabilities import is_printer_type
        from apps.machines.service_consumable_pools import _validate_pool
        _validate_pool(machine, locked, request.capability_payload if is_printer_type(machine.machine_type) else None)
        if request.reserved_quantity:
            raise ValidationError({"planned_quantity": "Consumable quantity is already reserved."})
        _apply(locked, actor, kind=MachineConsumableAdjustment.Kind.RESERVE, delta=-quantity,
               service_request=request, metering_unit=unit)
        request.run_consumable_pool = locked
        request.metering_unit = unit
        request.planned_quantity = quantity
        request.reserved_quantity = quantity
        if unit == MeteringUnit.WEIGHT:
            request.planned_grams = quantity
            request.reserved_grams = quantity
        request.save(update_fields=["run_consumable_pool", "metering_unit", "planned_quantity", "reserved_quantity", "planned_grams", "reserved_grams", "updated_at"])
        return request


def _is_generic_reservation(service_request):
    request = MachineServiceRequest.objects.select_related("run_consumable_pool").get(pk=service_request.pk)
    pool = request.run_consumable_pool
    unit = request.metering_unit or (metering_unit_for_pool(pool.unit) if pool else None) or MeteringUnit.WEIGHT
    return ((request.reserved_quantity is not None and unit != MeteringUnit.WEIGHT)
            or (pool is not None and pool.unit != "grams"))


def reconcile_request(legacy, service_request, actor, *, actual_grams=None, actual_quantity=None, reason=""):
    if actual_quantity is None:
        if not _is_generic_reservation(service_request):
            row = legacy(service_request, actor, actual_grams=actual_grams, reason=reason)
            row.metering_unit = MeteringUnit.WEIGHT
            row.actual_consumed_quantity = row.actual_consumed_grams
            row.reserved_quantity = row.reserved_grams
            row.save(update_fields=["metering_unit", "actual_consumed_quantity", "reserved_quantity", "updated_at"])
            return row
    with transaction.atomic():
        request = MachineServiceRequest.objects.select_for_update(of=("self",)).select_related("run_consumable_pool").get(pk=service_request.pk)
        if request.run_consumable_pool_id is None:
            return request
        actual = _quantity(request.reserved_quantity if actual_quantity is None else actual_quantity, "actual_quantity")
        pool = request.run_consumable_pool.__class__.objects.select_for_update(of=("self",)).get(pk=request.run_consumable_pool_id)
        unit = request.metering_unit or metering_unit_for_pool(pool.unit)
        if unit not in MeteringUnit.values:
            raise ValidationError({"metering_unit": "Unsupported metering unit."})
        reserved = request.reserved_quantity or Decimal("0")
        delta = reserved - actual
        if delta:
            _apply(pool, actor, kind=MachineConsumableAdjustment.Kind.RECONCILE, delta=delta,
                   service_request=request, reason=reason, metering_unit=unit)
        request.actual_consumed_quantity = actual
        request.reserved_quantity = Decimal("0")
        if unit == MeteringUnit.WEIGHT:
            request.actual_consumed_grams = actual
            request.reserved_grams = Decimal("0")
        request.save(update_fields=["actual_consumed_quantity", "reserved_quantity", "actual_consumed_grams", "reserved_grams", "updated_at"])
        return request

