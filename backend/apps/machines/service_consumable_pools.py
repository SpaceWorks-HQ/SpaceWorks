"""Row-locked accounting authority for pooled machine consumables."""

from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework.exceptions import ValidationError

from apps.audit import services as audit
from apps.machines.consumable_scope import pool_serves_machine
from apps.machines.models import (
    Machine,
    MachineConsumableAdjustment,
    MachineConsumablePool,
    MachineServiceRequest,
    MachineType,
    MachineUsageEntry,
)
from apps.machines.printer_capabilities import is_printer_type, validate_pool


def _grams(value, field):
    try:
        parsed = Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValidationError({field: "Enter a valid gram amount."}) from exc
    if not parsed.is_finite() or parsed < 0:
        raise ValidationError({field: "Enter a non-negative gram amount."})
    return parsed


def _audit(actor, action, pool, *, target=None, **meta):
    audit.record(actor, action, makerspace=pool.makerspace, target=target or pool, meta=meta)


def _validate_pool(machine, pool, payload=None):
    try:
        validate_pool(machine, pool, payload)
    except DjangoValidationError as exc:
        raise ValidationError(exc.message_dict if hasattr(exc, "message_dict") else exc.messages) from exc


@transaction.atomic
def create_pool(makerspace, actor, *, material, initial_grams, machine=None, machine_type=None, color="", color_hex="", brand="", lot_code="", low_threshold_grams=None, is_public=True):
    initial = _grams(initial_grams, "initial_grams")
    if not str(material).strip():
        raise ValidationError({"material": "Material is required."})
    color_hex = str(color_hex).strip().lower()
    if color_hex and (len(color_hex) != 7 or color_hex[0] != "#" or any(char not in "0123456789abcdef" for char in color_hex[1:])):
        raise ValidationError({"color_hex": "Enter a colour in #RRGGBB format."})
    if machine is not None and machine_type is not None:
        raise ValidationError({"machine_type": "Choose either machine or machine_type, not both."})
    if machine is not None:
        machine = Machine.objects.select_for_update().get(pk=machine.pk)
        if machine.makerspace_id != makerspace.pk:
            raise ValidationError({"machine": "Machine must belong to this makerspace."})
    if machine_type is not None:
        machine_type = MachineType.objects.select_for_update().get(pk=machine_type.pk)
        local_type = machine_type.makerspace_id == makerspace.pk
        global_builtin = machine_type.makerspace_id is None and machine_type.is_builtin
        if not (local_type or global_builtin):
            raise ValidationError({
                "machine_type": "Machine type must be global or belong to this makerspace."
            })
    threshold = None if low_threshold_grams is None else _grams(low_threshold_grams, "low_threshold_grams")
    pool = MachineConsumablePool.objects.create(
        makerspace=makerspace, machine=machine, machine_type=machine_type,
        material=str(material).strip(), color=str(color).strip(), color_hex=color_hex,
        brand=str(brand).strip(), lot_code=str(lot_code).strip(), initial_grams=initial,
        remaining_grams=initial, low_threshold_grams=threshold, is_public=is_public,
        created_by=actor,
    )
    if machine is not None:
        _validate_pool(machine, pool)
    scope = "machine" if machine is not None else "machine_type" if machine_type is not None else "makerspace"
    _audit(
        actor,
        "machine_consumable_pool.created",
        pool,
        pool_id=pool.pk,
        initial_grams=str(initial),
        scope=scope,
        machine_id=getattr(machine, "pk", None),
        machine_type_id=getattr(machine_type, "pk", None),
        is_public=is_public,
    )
    return pool


def _locked_pool(pool):
    return MachineConsumablePool.objects.select_for_update(of=("self",)).select_related("makerspace", "machine").get(pk=pool.pk)


def _apply(pool, actor, *, kind, delta, service_request=None, usage_entry=None, reason=""):
    delta = Decimal(delta).quantize(Decimal("0.01"))
    after = pool.remaining_grams + delta
    if after < 0:
        raise ValidationError({"grams": f"Only {pool.remaining_grams} grams remain."})
    if after > pool.initial_grams:
        raise ValidationError({"grams": "Adjustment would exceed initial grams."})
    row = MachineConsumableAdjustment.objects.create(
        consumable_pool=pool, makerspace=pool.makerspace, kind=kind, quantity_delta=delta,
        service_request=service_request, usage_entry=usage_entry, reason=str(reason).strip(), created_by=actor,
    )
    pool.remaining_grams = after
    pool.save(update_fields=["remaining_grams", "updated_at"])
    _audit(actor, f"machine_consumable_pool.{kind}", pool, target=row, pool_id=pool.pk,
           adjustment_id=row.pk, quantity_delta=str(delta), remaining_grams=str(after),
           request_id=getattr(service_request, "pk", None), usage_entry_id=getattr(usage_entry, "pk", None))
    if delta < 0:
        from apps.machines.low_stock import maybe_flag_low_stock
        maybe_flag_low_stock(actor, pool)
    return row


@transaction.atomic
def reserve_for_request(service_request, actor, *, pool, planned_grams, machine):
    request = MachineServiceRequest.objects.select_for_update(of=("self",)).select_related("queue__makerspace", "bucket__machine__makerspace").get(pk=service_request.pk)
    locked = _locked_pool(pool)
    planned = _grams(planned_grams, "planned_grams")
    if not planned:
        raise ValidationError({"planned_grams": "Planned grams must be greater than zero."})
    if not locked.is_active:
        raise ValidationError({"consumable_pool": "Consumable pool is retired."})
    # `pool_serves_machine` ties the pool to the MACHINE's tenant; the check it replaced tied it to
    # the REQUEST's. Neither implies the other here -- nothing in this function validates the
    # machine against the request -- so both are asserted rather than trading one for the other.
    if locked.makerspace_id != request.makerspace_id or not pool_serves_machine(locked, machine):
        raise ValidationError({"consumable_pool": "Consumable pool is incompatible with this machine service request."})
    _validate_pool(machine, locked, request.capability_payload if is_printer_type(machine.machine_type) else None)
    if request.reserved_grams:
        raise ValidationError({"planned_grams": "Consumable grams are already reserved."})
    _apply(locked, actor, kind=MachineConsumableAdjustment.Kind.RESERVE, delta=-planned, service_request=request)
    request.run_consumable_pool = locked
    request.planned_grams = planned
    request.reserved_grams = planned
    request.save(update_fields=["run_consumable_pool", "planned_grams", "reserved_grams", "updated_at"])
    return request


@transaction.atomic
def reconcile_request(service_request, actor, *, actual_grams, reason=""):
    request = MachineServiceRequest.objects.select_for_update(of=("self",)).select_related("run_consumable_pool", "queue__makerspace", "bucket__machine__makerspace").get(pk=service_request.pk)
    if request.run_consumable_pool_id is None:
        return request
    actual = _grams(actual_grams, "actual_grams")
    pool = _locked_pool(request.run_consumable_pool)
    delta = request.reserved_grams - actual
    if delta:
        _apply(pool, actor, kind=MachineConsumableAdjustment.Kind.RECONCILE, delta=delta, service_request=request, reason=reason)
    request.actual_consumed_grams = actual
    request.reserved_grams = Decimal("0")
    request.save(update_fields=["actual_consumed_grams", "reserved_grams", "updated_at"])
    return request


@transaction.atomic
def correct_pool(pool, actor, *, quantity_delta, reason):
    if not str(reason).strip():
        raise ValidationError({"reason": "A correction reason is required."})
    locked = _locked_pool(pool)
    signed = _signed_grams(quantity_delta, "quantity_delta")
    delta = abs(signed)
    if signed < 0:
        delta = -delta
    if not delta:
        raise ValidationError({"quantity_delta": "Adjustment cannot be zero."})
    _apply(locked, actor, kind=MachineConsumableAdjustment.Kind.CORRECTION, delta=delta, reason=reason)
    return locked


@transaction.atomic
def set_pool_visibility(pool, actor, *, is_public):
    locked = _locked_pool(pool)
    if locked.is_public == is_public:
        return locked
    previous = locked.is_public
    locked.is_public = is_public
    locked.save(update_fields=["is_public", "updated_at"])
    _audit(
        actor, "machine_consumable_pool.visibility_changed", locked, pool_id=locked.pk,
        **{"from": previous, "to": is_public},
    )
    return locked


def _signed_grams(value, field):
    try:
        parsed = Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValidationError({field: "Enter a valid gram amount."}) from exc
    if not parsed.is_finite():
        raise ValidationError({field: "Enter a finite gram amount."})
    return parsed


@transaction.atomic
def retire_pool(pool, actor, *, reason):
    if not str(reason).strip():
        raise ValidationError({"reason": "A retirement reason is required."})
    locked = _locked_pool(pool)
    if not locked.is_active:
        return locked
    if locked.remaining_grams:
        _apply(locked, actor, kind=MachineConsumableAdjustment.Kind.RETIRE, delta=-locked.remaining_grams, reason=reason)
    locked.is_active = False
    locked.save(update_fields=["is_active", "updated_at"])
    _audit(actor, "machine_consumable_pool.retired", locked, pool_id=locked.pk)
    return locked


@transaction.atomic
def log_typed_manual_usage(machine, actor, *, duration_minutes, outcome, percent_complete, reason="", grams=0, quantity=None, metering_unit=None, pool=None, service_request=None, note=""):
    machine = Machine.objects.select_for_update().select_related("makerspace").get(pk=machine.pk)
    if outcome not in {"success", "failed"}:
        raise ValidationError({"outcome": "Outcome must be success or failed."})
    if not isinstance(duration_minutes, int) or duration_minutes < 0:
        raise ValidationError({"duration_minutes": "Duration must be a non-negative whole number."})
    if not isinstance(percent_complete, int) or not 0 <= percent_complete <= 100:
        raise ValidationError({"percent_complete": "Percent must be between 0 and 100."})
    if outcome == "failed" and not str(reason).strip():
        raise ValidationError({"reason": "A failure reason is required."})
    grams = _grams(grams, "grams")
    quantity = grams if quantity is None else _grams(quantity, "quantity")
    if pool is not None:
        pool = _locked_pool(pool)
        if not pool_serves_machine(pool, machine):
            raise ValidationError({"consumable_pool": "Consumable pool is incompatible with this machine."})
        _validate_pool(machine, pool)
    if service_request is not None:
        service_request = MachineServiceRequest.objects.select_for_update().get(pk=service_request.pk)
        if service_request.makerspace_id != machine.makerspace_id:
            raise ValidationError({"service_request": "Service request must belong to this makerspace."})
    usage_unit = metering_unit or (metering_unit_for_pool(pool.unit) if pool else None) or MeteringUnit.WEIGHT
    if usage_unit not in MeteringUnit.values:
        raise ValidationError({"metering_unit": "Unsupported metering unit."})
    if pool is not None and metering_unit_for_pool(pool.unit) != usage_unit:
        raise ValidationError({"metering_unit": "Consumable pool unit is incompatible with this metering unit."})
    entry = MachineUsageEntry.objects.create(
        machine=machine, hours=(Decimal(duration_minutes) * Decimal(percent_complete) / Decimal("6000")).quantize(Decimal("0.01")),
        source=MachineUsageEntry.Source.TYPED_MANUAL, service_request=service_request, consumable_pool=pool,
        duration_minutes=duration_minutes, outcome=outcome, percent_complete=percent_complete,
        reason=str(reason).strip(), consumed_grams=grams, note=str(note).strip(), logged_by=actor,
        metering_unit=usage_unit, consumed_quantity=quantity,
    )
    if quantity:
        if pool is None:
            raise ValidationError({"consumable_pool": "A consumable pool is required when quantity is recorded."})
        _apply(pool, actor, kind=MachineConsumableAdjustment.Kind.MANUAL, delta=-quantity, usage_entry=entry, service_request=service_request, reason=reason, metering_unit=usage_unit)
    audit.record(
        actor, "machine.typed_usage_logged", makerspace=machine.makerspace, target=entry,
        meta={"machine_id": machine.pk, "usage_entry_id": entry.pk, "duration_minutes": duration_minutes,
              "outcome": outcome, "grams": str(grams), "quantity": str(quantity), "metering_unit": usage_unit},
    )
    return entry

from apps.machines.metering import MeteringUnit, metering_unit_for_pool
from apps.machines.service_metering import _apply as _metered_apply
from apps.machines.service_metering import reconcile_request as _metered_reconcile
from apps.machines.service_metering import reserve_for_request as _metered_reserve

_legacy_reconcile_request = reconcile_request
_legacy_reserve_for_request = reserve_for_request


def _apply(*args, **kwargs):
    return _metered_apply(*args, **kwargs)


def reserve_for_request(service_request, actor, *, pool, planned_grams=None, planned_quantity=None, machine):
    return _metered_reserve(_legacy_reserve_for_request, service_request, actor, pool=pool, planned_grams=planned_grams, planned_quantity=planned_quantity, machine=machine)


def reconcile_request(service_request, actor, *, actual_grams=None, actual_quantity=None, reason=""):
    return _metered_reconcile(_legacy_reconcile_request, service_request, actor, actual_grams=actual_grams, actual_quantity=actual_quantity, reason=reason)
_legacy_create_pool = create_pool


@transaction.atomic
def create_pool(makerspace, actor, *, material, initial_grams=None, quantity=None, machine=None, machine_type=None, color="", color_hex="", brand="", lot_code="", low_threshold_grams=None, unit="grams", is_public=True):
    from apps.machines.metering import ConsumablePoolUnit
    if unit not in ConsumablePoolUnit.values:
        raise ValidationError({"unit": "Unsupported consumable pool unit."})
    if initial_grams is None:
        initial_grams = quantity
    elif quantity is not None:
        raise ValidationError({"quantity": "Provide quantity or initial_grams, not both."})
    if initial_grams is None:
        raise ValidationError({"quantity": "A starting quantity is required."})
    scoped_type = machine.machine_type if machine is not None else machine_type
    if is_printer_type(scoped_type) and unit != ConsumablePoolUnit.GRAMS:
        raise ValidationError({"unit": "Printer consumable pools use grams."})
    pool = _legacy_create_pool(makerspace, actor, material=material, initial_grams=initial_grams,
                               machine=machine, machine_type=machine_type, color=color, color_hex=color_hex, brand=brand,
                               lot_code=lot_code, low_threshold_grams=low_threshold_grams,
                               is_public=is_public)
    if unit != ConsumablePoolUnit.GRAMS:
        pool.unit = unit
        pool.save(update_fields=["unit", "updated_at"])
    return pool
