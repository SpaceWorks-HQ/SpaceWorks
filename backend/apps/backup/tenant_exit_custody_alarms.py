"""Decision-19b alarm intents and dispatch for Lane D custody."""

import logging
from datetime import timedelta

from django.db import transaction
from django.db.models import Exists, Max, OuterRef
from django.utils import timezone

from apps.makerspaces.platform import module_enabled

from .custody_alarm_dispatch import (
    MAX_ATTEMPTS,
    MAX_ROWS_PER_SWEEP,
    deliver_claimable_rows,
)
from .custody_alarm_recipients import (
    mailable_tenant_recipients,
    operator_recipients,
    tenant_non_operator_repair_recipients,
)
from .models import (
    MakerspaceTenantExitCustodyState as CustodyState,
    TenantExitCustodyAlarmDelivery as Delivery,
)


logger = logging.getLogger(__name__)
ALARM_STATES = (
    CustodyState.State.DEGRADED_ONE_RECIPIENT,
    CustodyState.State.FLOOR_BREACHED_ZERO,
)
DEGRADED_REMINDER = timedelta(days=7)
ZERO_REMINDER = timedelta(days=1)


def ensure_delivery_intents_locked(state, *, cycle=0):
    """Create required current-revision intents while `state` is locked."""
    if state.state not in ALARM_STATES:
        return ()
    repair = tenant_non_operator_repair_recipients(state.makerspace)
    mailable = mailable_tenant_recipients(state.makerspace, repair)
    rows = _tenant_intents(state, cycle, mailable)
    if _operator_required(state, repair, mailable):
        operators = operator_recipients()
        rows.extend(_operator_intents(state, cycle, operators))
        if not operators:
            _log_no_operator_address(state, cycle)
    return tuple(Delivery.objects.bulk_create(rows, ignore_conflicts=True))


def ensure_delivery_intents(state_id):
    with transaction.atomic():
        state = CustodyState.objects.select_for_update().get(pk=state_id)
        if state.state not in ALARM_STATES:
            return ()
        cycle = _resolve_cycle_locked(state)
        return ensure_delivery_intents_locked(state, cycle=cycle)


def deliver_tenant_exit_custody_alarms(*, makerspace_id=None):
    states = CustodyState.objects.filter(state__in=ALARM_STATES)
    if makerspace_id is not None:
        states = states.filter(makerspace_id=makerspace_id)
    state_ids = tuple(states.order_by("makerspace_id").values_list("pk", flat=True))
    for state_id in state_ids:
        try:
            ensure_delivery_intents(state_id)
        except Exception:
            logger.exception(
                "tenant_exit_custody_alarm_intent_failed",
                extra={"custody_state_id": state_id},
            )
    delivered = deliver_claimable_rows(
        makerspace_id=makerspace_id,
        delivery_model=Delivery,
        state_model=CustodyState,
        event="tenant_exit_custody_alarm",
        custody_label="Tenant exit",
    )
    for state_id in state_ids:
        _reconcile_exhausted(state_id)
    remaining = max(0, MAX_ROWS_PER_SWEEP - delivered)
    if remaining:
        delivered += deliver_claimable_rows(
            makerspace_id=makerspace_id,
            limit=remaining,
            delivery_model=Delivery,
            state_model=CustodyState,
            event="tenant_exit_custody_alarm",
            custody_label="Tenant exit",
        )
    return delivered


def required_intents_present_locked(state):
    """Verify the durable current revision can retry/escalate after commit."""
    if state.state == CustodyState.State.HEALTHY:
        return True
    repair = tenant_non_operator_repair_recipients(state.makerspace)
    mailable = mailable_tenant_recipients(state.makerspace, repair)
    required = set()
    if module_enabled(state.makerspace, "notifications"):
        required.add((Delivery.Channel.TENANT_INAPP, None))
    required.update((Delivery.Channel.TENANT_EMAIL, user.pk) for user in mailable)
    operators = operator_recipients() if _operator_required(state, repair, mailable) else ()
    required.update((Delivery.Channel.OPERATOR_EMAIL, user.pk) for user in operators)
    if not required or (_operator_required(state, repair, mailable) and not operators):
        return False
    rows = tuple(
        Delivery.objects.filter(
            makerspace_id=state.makerspace_id,
            alarm_revision=state.alarm_revision,
            cycle=0,
        )
    )
    actual = {(row.channel, row.recipient_ref) for row in rows}
    if not required <= actual:
        return False
    by_key = {(row.channel, row.recipient_ref): row for row in rows}
    operator_keys = {
        key for key in required if key[0] == Delivery.Channel.OPERATOR_EMAIL
    }
    if any(not _can_finish(by_key[key]) for key in operator_keys):
        return False
    exhausted_tenant = any(
        key[0] in (Delivery.Channel.TENANT_EMAIL, Delivery.Channel.TENANT_INAPP)
        and not _can_finish(by_key[key])
        for key in required
    )
    if exhausted_tenant:
        operator_rows = tuple(
            row for row in rows if row.channel == Delivery.Channel.OPERATOR_EMAIL
        )
        return bool(operator_rows) and all(_can_finish(row) for row in operator_rows)
    return True


def _can_finish(row):
    return row.status == Delivery.Status.SENT or (
        row.status != Delivery.Status.EXHAUSTED and row.attempts < MAX_ATTEMPTS
    )


def readiness_counts():
    alarming = CustodyState.objects.filter(state__in=ALARM_STATES)
    current = Delivery.objects.filter(
        makerspace_id=OuterRef("makerspace_id"),
        alarm_revision=OuterRef("alarm_revision"),
    )
    missing = alarming.annotate(has_intent=Exists(current)).filter(has_intent=False)
    incapable = sum(not _state_ready(state) for state in alarming.select_related("makerspace"))
    return {
        "below_floor_makerspaces": alarming.count(),
        "zero_recipient_makerspaces": alarming.filter(
            state=CustodyState.State.FLOOR_BREACHED_ZERO
        ).count(),
        "missing_current_revision_intents": missing.count(),
        "incapable_outboxes": incapable,
    }


def _state_ready(state):
    return required_intents_present_locked(state)


def _resolve_cycle_locked(state):
    rows = Delivery.objects.filter(
        makerspace_id=state.makerspace_id,
        alarm_revision=state.alarm_revision,
    )
    current = rows.aggregate(cycle=Max("cycle"))["cycle"]
    if current is None:
        return 0
    latest = rows.filter(cycle=current).aggregate(created=Max("created_at"))["created"]
    interval = ZERO_REMINDER if state.state == CustodyState.State.FLOOR_BREACHED_ZERO else DEGRADED_REMINDER
    return current + 1 if latest and latest <= timezone.now() - interval else current


def _tenant_intents(state, cycle, mailable):
    rows = []
    if module_enabled(state.makerspace, "notifications"):
        rows.append(_delivery(state, cycle, Delivery.Channel.TENANT_INAPP))
    rows.extend(
        _delivery(state, cycle, Delivery.Channel.TENANT_EMAIL, user=user)
        for user in mailable
    )
    return rows


def _operator_intents(state, cycle, operators):
    return [
        _delivery(state, cycle, Delivery.Channel.OPERATOR_EMAIL, user=user)
        for user in operators
    ]


def _delivery(state, cycle, channel, *, user=None):
    return Delivery(
        makerspace_id=state.makerspace_id,
        alarm_revision=state.alarm_revision,
        cycle=cycle,
        channel=channel,
        recipient_user=user,
        recipient_ref=None if user is None else user.pk,
    )


def _operator_required(state, repair, mailable):
    return (
        state.state == CustodyState.State.FLOOR_BREACHED_ZERO
        or not repair
        or not mailable
    )


def _reconcile_exhausted(state_id):
    with transaction.atomic():
        state = CustodyState.objects.select_for_update().get(pk=state_id)
        if state.state not in ALARM_STATES:
            return
        cycle = Delivery.objects.filter(
            makerspace_id=state.makerspace_id,
            alarm_revision=state.alarm_revision,
        ).aggregate(cycle=Max("cycle"))["cycle"]
        if cycle is None:
            return
        tenant = Delivery.objects.filter(
            makerspace_id=state.makerspace_id,
            alarm_revision=state.alarm_revision,
            cycle=cycle,
            channel=Delivery.Channel.TENANT_EMAIL,
        )
        if not tenant.exists() or tenant.exclude(status=Delivery.Status.EXHAUSTED).exists():
            return
        operators = operator_recipients()
        Delivery.objects.bulk_create(
            _operator_intents(state, cycle, operators), ignore_conflicts=True
        )
        if not operators:
            _log_no_operator_address(state, cycle)


def _log_no_operator_address(state, cycle):
    logger.error(
        "tenant_exit_custody_alarm_no_operator_address",
        extra={
            "makerspace_id": state.makerspace_id,
            "alarm_revision": state.alarm_revision,
            "cycle": cycle,
            "custody_state": state.state,
        },
    )
