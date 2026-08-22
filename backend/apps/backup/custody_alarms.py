"""Recoverable archive-custody alarm delivery.

Delivery is AT-LEAST-ONCE: a duplicate is possible; a drop is not. A worker can
die after SMTP acceptance and before recording success, so durable intent is created
under the custody-row lock and claimed rows dispatch only after that transaction.
"""

import logging
from datetime import timedelta

from django.db import transaction
from django.db.models import Exists, Max, OuterRef
from django.utils import timezone

from apps.makerspaces.platform import module_enabled

from .custody_alarm_dispatch import (
    CLAIM_LEASE,
    MAX_ATTEMPTS,
    MAX_ROWS_PER_SWEEP,
    SEND_TIMEOUT,
    deliver_claimable_rows,
)
from .custody_alarm_recipients import (
    mailable_tenant_recipients,
    operator_recipients,
    tenant_non_operator_repair_recipients,
)
from .models import (
    ArchiveCustodyAlarmDelivery,
    MakerspaceArchiveCustodyState,
)


__all__ = (
    "CLAIM_LEASE",
    "MAX_ATTEMPTS",
    "MAX_ROWS_PER_SWEEP",
    "SEND_TIMEOUT",
    "deliver_archive_custody_alarms",
    "tenant_non_operator_repair_recipients",
)


logger = logging.getLogger(__name__)
ALARM_STATES = (
    MakerspaceArchiveCustodyState.State.DEGRADED_ONE_RECIPIENT,
    MakerspaceArchiveCustodyState.State.FLOOR_BREACHED_ZERO,
)
DEGRADED_REMINDER = timedelta(days=7)
ZERO_REMINDER = timedelta(days=1)


def deliver_archive_custody_alarms(*, makerspace_id=None):
    state_ids = list(
        MakerspaceArchiveCustodyState.objects.filter(state__in=ALARM_STATES)
        .filter(**({"makerspace_id": makerspace_id} if makerspace_id else {}))
        .order_by("makerspace_id")
        .values_list("pk", flat=True)
    )
    for state_id in state_ids:
        try:
            _ensure_delivery_intents(state_id)
        except Exception:
            logger.exception(
                "archive_custody_alarm_intent_failed",
                extra={"custody_state_id": state_id},
            )

    delivered = deliver_claimable_rows(makerspace_id=makerspace_id)

    for state_id in state_ids:
        try:
            _reconcile_exhausted_tenant_deliveries(state_id)
        except Exception:
            logger.exception(
                "archive_custody_alarm_reconciliation_failed",
                extra={"custody_state_id": state_id},
            )

    remaining = max(0, MAX_ROWS_PER_SWEEP - delivered)
    if remaining:
        delivered += deliver_claimable_rows(
            makerspace_id=makerspace_id,
            limit=remaining,
        )
    return delivered


def _ensure_delivery_intents(state_id):
    with transaction.atomic():
        state = (
            MakerspaceArchiveCustodyState.objects.select_for_update()
            .select_related("makerspace")
            .get(pk=state_id)
        )
        if state.state not in ALARM_STATES:
            return
        cycle = _resolve_cycle_under_lock(state)
        repair = tenant_non_operator_repair_recipients(state.makerspace)
        mailable = mailable_tenant_recipients(state.makerspace, repair)
        rows = _tenant_intents(state, cycle, mailable)

        if _resolve_time_operator_required(state, repair, mailable):
            operators = operator_recipients()
            rows.extend(_operator_intents(state, cycle, operators))
            if not operators:
                _log_no_operator_address(state, cycle)

        ArchiveCustodyAlarmDelivery.objects.bulk_create(
            rows,
            ignore_conflicts=True,
        )


def _resolve_cycle_under_lock(state):
    current = ArchiveCustodyAlarmDelivery.objects.filter(
        makerspace_id=state.makerspace_id,
        alarm_revision=state.alarm_revision,
    ).aggregate(cycle=Max("cycle"))["cycle"]
    if current is None:
        return 0
    latest = ArchiveCustodyAlarmDelivery.objects.filter(
        makerspace_id=state.makerspace_id,
        alarm_revision=state.alarm_revision,
        cycle=current,
    ).aggregate(created=Max("created_at"))["created"]
    interval = (
        ZERO_REMINDER
        if state.state == MakerspaceArchiveCustodyState.State.FLOOR_BREACHED_ZERO
        else DEGRADED_REMINDER
    )
    return current + 1 if latest and latest <= timezone.now() - interval else current


def _tenant_intents(state, cycle, mailable):
    rows = []
    if module_enabled(state.makerspace, "notifications"):
        rows.append(
            _delivery(state, cycle, ArchiveCustodyAlarmDelivery.Channel.TENANT_INAPP)
        )
    rows.extend(
        _delivery(
            state,
            cycle,
            ArchiveCustodyAlarmDelivery.Channel.TENANT_EMAIL,
            user=user,
        )
        for user in mailable
    )
    return rows


def _operator_intents(state, cycle, operators):
    return [
        _delivery(
            state,
            cycle,
            ArchiveCustodyAlarmDelivery.Channel.OPERATOR_EMAIL,
            user=user,
        )
        for user in operators
    ]


def _delivery(state, cycle, channel, *, user=None):
    return ArchiveCustodyAlarmDelivery(
        makerspace_id=state.makerspace_id,
        alarm_revision=state.alarm_revision,
        cycle=cycle,
        channel=channel,
        recipient_user=user,
        recipient_ref=None if user is None else user.pk,
    )


def _resolve_time_operator_required(state, repair, mailable):
    return (
        state.state == MakerspaceArchiveCustodyState.State.FLOOR_BREACHED_ZERO
        or not repair
        or not mailable
    )


def _reconcile_exhausted_tenant_deliveries(state_id):
    # Ordering is deliberate: lock/re-read state, resolve the current cycle under that
    # lock, then make both exhaustion observations before the conflict-safe insert.
    with transaction.atomic():
        state = (
            MakerspaceArchiveCustodyState.objects.select_for_update()
            .select_related("makerspace")
            .get(pk=state_id)
        )
        if state.state not in ALARM_STATES:
            return
        revision = state.alarm_revision
        current_cycle = ArchiveCustodyAlarmDelivery.objects.filter(
            makerspace_id=state.makerspace_id,
            alarm_revision=revision,
        ).aggregate(cycle=Max("cycle"))["cycle"]
        if current_cycle is None:
            return
        tenant_rows = ArchiveCustodyAlarmDelivery.objects.filter(
            makerspace_id=state.makerspace_id,
            alarm_revision=revision,
            cycle=current_cycle,
            channel=ArchiveCustodyAlarmDelivery.Channel.TENANT_EMAIL,
        )
        if tenant_rows.count() < 1 or tenant_rows.exclude(
            status=ArchiveCustodyAlarmDelivery.Status.EXHAUSTED
        ).exists():
            return
        operators = operator_recipients()
        if not operators:
            _log_no_operator_address(state, current_cycle)
            return
        ArchiveCustodyAlarmDelivery.objects.bulk_create(
            _operator_intents(state, current_cycle, operators),
            ignore_conflicts=True,
        )


def readiness_counts():
    alarming = MakerspaceArchiveCustodyState.objects.filter(state__in=ALARM_STATES)
    sent_delivery = ArchiveCustodyAlarmDelivery.objects.filter(
        makerspace_id=OuterRef("makerspace_id"),
        alarm_revision=OuterRef("alarm_revision"),
        status=ArchiveCustodyAlarmDelivery.Status.SENT,
    )
    undelivered = alarming.annotate(has_delivery=Exists(sent_delivery)).filter(
        has_delivery=False
    ).count()
    return {
        "below_floor_makerspaces": alarming.count(),
        "zero_recipient_makerspaces": alarming.filter(
            state=MakerspaceArchiveCustodyState.State.FLOOR_BREACHED_ZERO
        ).count(),
        "undelivered_alarms": undelivered,
        "alarms_with_no_operator_address": _no_operator_address_count(alarming),
    }


def _no_operator_address_count(alarming):
    if operator_recipients():
        return 0
    count = 0
    for state in alarming.select_related("makerspace"):
        repair = tenant_non_operator_repair_recipients(state.makerspace)
        mailable = mailable_tenant_recipients(state.makerspace, repair)
        required = _resolve_time_operator_required(state, repair, mailable)
        if not required:
            current_cycle = ArchiveCustodyAlarmDelivery.objects.filter(
                makerspace_id=state.makerspace_id,
                alarm_revision=state.alarm_revision,
            ).aggregate(cycle=Max("cycle"))["cycle"]
            if current_cycle is not None:
                tenant = ArchiveCustodyAlarmDelivery.objects.filter(
                    makerspace_id=state.makerspace_id,
                    alarm_revision=state.alarm_revision,
                    cycle=current_cycle,
                    channel=ArchiveCustodyAlarmDelivery.Channel.TENANT_EMAIL,
                )
                required = tenant.exists() and not tenant.exclude(
                    status=ArchiveCustodyAlarmDelivery.Status.EXHAUSTED
                ).exists()
        count += int(required)
    return count


def _log_no_operator_address(state, cycle):
    logger.error(
        "archive_custody_alarm_no_operator_address",
        extra={
            "makerspace_id": state.makerspace_id,
            "alarm_revision": state.alarm_revision,
            "cycle": cycle,
            "custody_state": state.state,
        },
    )
