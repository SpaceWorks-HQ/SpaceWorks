from datetime import timedelta

import pytest
from django.db.models import Max
from django.utils import timezone

from apps.backup import custody_alarms
from apps.backup.custody import with_makerspace_custody_lock
from apps.backup.custody_alarm_dispatch import (
    CLAIM_LEASE,
    MAX_ATTEMPTS,
    deliver_claimable_rows,
)
from apps.backup.models import (
    ArchiveCustodyAlarmDelivery as Delivery,
    MakerspaceArchiveCustodyState as CustodyState,
    MakerspaceArchiveRecipient,
)
from apps.integrations.dispatch import email_module_blocks
from apps.integrations.models import EmailLog
from apps.makerspaces.models import Makerspace
from tests.backup.archive_custody_alarm_test_helpers import (
    channels as _channels,
    manager as _manager,
    operator as _operator,
    sent_dispatch as _sent_dispatch,
    space as _space,
)


pytestmark = pytest.mark.django_db


def test_superadmin_on_zero_is_not_applicable_or_alarmable(monkeypatch):
    space = Makerspace.objects.create(name="On", slug="alarm-on")
    with with_makerspace_custody_lock(space.pk):
        pass
    state = CustodyState.objects.get(makerspace=space)

    monkeypatch.setattr("apps.backup.custody_alarm_dispatch.dispatch_email", _sent_dispatch)
    custody_alarms.deliver_archive_custody_alarms(makerspace_id=space.pk)

    assert state.state == CustodyState.State.NOT_APPLICABLE
    assert state.alarm_revision == 1
    assert custody_alarms.readiness_counts()["below_floor_makerspaces"] == 0
    assert not Delivery.objects.filter(makerspace=space).exists()


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        (CustodyState.State.DEGRADED_ONE_RECIPIENT, {"tenant_inapp", "tenant_email"}),
        (
            CustodyState.State.FLOOR_BREACHED_ZERO,
            {"tenant_inapp", "tenant_email", "operator_email"},
        ),
    ],
)
def test_off_alarm_audiences_follow_custody_severity(monkeypatch, state, expected):
    space = _space(f"audience-{state}", state)
    _manager(space)
    _operator(f"operator-{state}")
    monkeypatch.setattr("apps.backup.custody_alarm_dispatch.dispatch_email", _sent_dispatch)

    custody_alarms.deliver_archive_custody_alarms(makerspace_id=space.pk)

    assert _channels(space) == expected
    assert not Delivery.objects.filter(makerspace=space).exclude(status="sent").exists()


def test_degraded_zero_degraded_transitions_have_distinct_revisions(monkeypatch):
    monkeypatch.setattr(
        "apps.backup.tasks.deliver_archive_custody_alarms_task.delay", lambda *_: None
    )
    space = Makerspace.objects.create(
        name="Transitions", slug="alarm-transitions", superadmin_access_enabled=False
    )
    _manager(space)
    _operator("transition-operator")
    recipients = [
        MakerspaceArchiveRecipient.objects.create(
            makerspace=space,
            public_recipient=f"age1transition{index}",
            fingerprint=f"{index:064x}",
            label=str(index),
            verified_at=timezone.now() if index < 2 else None,
        )
        for index in range(3)
    ]
    with with_makerspace_custody_lock(space.pk):
        pass
    revisions = []
    for recipient in recipients[:2]:
        with with_makerspace_custody_lock(space.pk) as custody:
            locked = custody.recipient(recipient.pk)
            locked.compromised_at = timezone.now()
            locked.save(update_fields=("compromised_at",))
        state = CustodyState.objects.get(makerspace=space)
        custody_alarms._ensure_delivery_intents(state.pk)
        revisions.append(state.alarm_revision)
    with with_makerspace_custody_lock(space.pk) as custody:
        locked = custody.recipient(recipients[2].pk)
        locked.verified_at = timezone.now()
        locked.save(update_fields=("verified_at",))
    state = CustodyState.objects.get(makerspace=space)
    custody_alarms._ensure_delivery_intents(state.pk)
    revisions.append(state.alarm_revision)

    assert state.alarm_episode == 1
    assert revisions == [2, 3, 4]
    assert set(Delivery.objects.values_list("alarm_revision", flat=True)) == set(revisions)


def test_on_off_reentry_starts_fresh_episode_and_alarm(monkeypatch):
    monkeypatch.setattr(
        "apps.backup.tasks.deliver_archive_custody_alarms_task.delay", lambda *_: None
    )
    space = Makerspace.objects.create(name="Reentry", slug="alarm-reentry")
    _manager(space)
    _operator("reentry-operator")
    revisions = []
    for enabled in (True, False, True, False):
        with with_makerspace_custody_lock(space.pk) as custody:
            custody.makerspace.superadmin_access_enabled = enabled
            custody.makerspace.save(update_fields=("superadmin_access_enabled",))
        state = CustodyState.objects.get(makerspace=space)
        if not enabled:
            custody_alarms._ensure_delivery_intents(state.pk)
            revisions.append(state.alarm_revision)

    assert state.state == CustodyState.State.FLOOR_BREACHED_ZERO
    assert state.alarm_episode == 2
    assert revisions == [2, 4]


@pytest.mark.parametrize("repair_kind", ["missing", "opted_out"])
def test_unreachable_tenant_escalates_without_overriding_opt_out(repair_kind):
    space = _space(f"unreachable-{repair_kind}", CustodyState.State.DEGRADED_ONE_RECIPIENT)
    if repair_kind == "opted_out":
        _manager(space, opted_in=False)
    operator = _operator(f"operator-{repair_kind}")

    custody_alarms._ensure_delivery_intents(space.archive_custody_state.pk)

    assert Delivery.objects.filter(
        makerspace=space, channel=Delivery.Channel.OPERATOR_EMAIL,
        recipient_ref=operator.pk,
    ).exists()
    assert not Delivery.objects.filter(
        makerspace=space, channel=Delivery.Channel.TENANT_EMAIL
    ).exists()


def test_email_module_cannot_suppress_custody_mail():
    space = Makerspace.objects.create(name="No email", slug="alarm-no-email", enabled_modules=[])
    assert email_module_blocks(space, "backup", "archive_custody_alarm") is False


def test_accepted_send_then_worker_death_is_retried_at_least_once(monkeypatch):
    space = _space("crash-window", CustodyState.State.DEGRADED_ONE_RECIPIENT, modules=())
    user = _manager(space)
    row = Delivery.objects.create(
        makerspace=space, alarm_revision=1, cycle=0,
        channel=Delivery.Channel.TENANT_EMAIL,
        recipient_user=user, recipient_ref=user.pk,
    )
    accepted = []

    def transport(**kwargs):
        accepted.append(kwargs["to_email"])
        if len(accepted) == 1:
            raise SystemExit("worker died after transport accepted the message")
        return _sent_dispatch(**kwargs)

    monkeypatch.setattr("apps.backup.custody_alarm_dispatch.dispatch_email", transport)
    with pytest.raises(SystemExit):
        deliver_claimable_rows(makerspace_id=space.pk, limit=1)
    row.refresh_from_db()
    assert row.status == Delivery.Status.SENDING
    assert row.attempts == 0
    Delivery.objects.filter(pk=row.pk).update(claimed_at=timezone.now() - CLAIM_LEASE)

    deliver_claimable_rows(makerspace_id=space.pk, limit=1)
    row.refresh_from_db()
    assert accepted == [user.email, user.email]
    assert row.status == Delivery.Status.SENT
    assert row.attempts == 0


def test_failures_retry_and_exhaust_only_after_observed_failures(monkeypatch):
    space = _space("exhaust", CustodyState.State.DEGRADED_ONE_RECIPIENT, modules=())
    user = _manager(space)
    row = Delivery.objects.create(
        makerspace=space, alarm_revision=1, cycle=0,
        channel=Delivery.Channel.TENANT_EMAIL,
        recipient_user=user, recipient_ref=user.pk,
    )

    def failed(**kwargs):
        log = _sent_dispatch(**kwargs)
        log.status, log.error = EmailLog.Status.FAILED, "provider unavailable"
        log.save(update_fields=("status", "error"))
        return log

    monkeypatch.setattr("apps.backup.custody_alarm_dispatch.dispatch_email", failed)
    for expected_attempts in range(1, MAX_ATTEMPTS + 1):
        deliver_claimable_rows(makerspace_id=space.pk, limit=1)
        row.refresh_from_db()
        assert row.attempts == expected_attempts
        if row.status == Delivery.Status.FAILED:
            Delivery.objects.filter(pk=row.pk).update(next_attempt_at=timezone.now())

    assert row.status == Delivery.Status.EXHAUSTED
    assert custody_alarms.readiness_counts()["undelivered_alarms"] == 1


def test_exhaustion_reconciliation_creates_operator_intent():
    space = _space("reconcile", CustodyState.State.DEGRADED_ONE_RECIPIENT, modules=())
    tenant, operator = _manager(space), _operator("reconcile-operator")
    Delivery.objects.create(
        makerspace=space, alarm_revision=1, cycle=0,
        channel=Delivery.Channel.TENANT_EMAIL,
        recipient_user=tenant, recipient_ref=tenant.pk,
        status=Delivery.Status.EXHAUSTED, attempts=MAX_ATTEMPTS,
    )

    custody_alarms._reconcile_exhausted_tenant_deliveries(space.archive_custody_state.pk)

    assert Delivery.objects.filter(
        makerspace=space, channel=Delivery.Channel.OPERATOR_EMAIL,
        recipient_ref=operator.pk,
    ).exists()


def test_missing_operator_address_creates_no_invalid_row_and_is_ready_visible(caplog):
    space = _space("no-operator", CustodyState.State.FLOOR_BREACHED_ZERO)
    _manager(space)
    custody_alarms._ensure_delivery_intents(space.archive_custody_state.pk)

    assert not Delivery.objects.filter(channel=Delivery.Channel.OPERATOR_EMAIL).exists()
    assert custody_alarms.readiness_counts()["alarms_with_no_operator_address"] == 1
    assert "archive_custody_alarm_no_operator_address" in caplog.text
    operator = _operator("late-operator")
    custody_alarms._ensure_delivery_intents(space.archive_custody_state.pk)
    assert Delivery.objects.filter(
        channel=Delivery.Channel.OPERATOR_EMAIL, recipient_ref=operator.pk
    ).exists()


def test_inapp_visibility_never_suppresses_operator_escalation():
    space = _space("inapp-escalates", CustodyState.State.DEGRADED_ONE_RECIPIENT)
    operator = _operator("inapp-operator")
    custody_alarms._ensure_delivery_intents(space.archive_custody_state.pk)
    assert _channels(space) == {Delivery.Channel.TENANT_INAPP, Delivery.Channel.OPERATOR_EMAIL}
    assert Delivery.objects.filter(recipient_ref=operator.pk).exists()


def test_intent_resolution_is_idempotent():
    space = _space("idempotent", CustodyState.State.DEGRADED_ONE_RECIPIENT)
    _manager(space)
    state_id = space.archive_custody_state.pk
    custody_alarms._ensure_delivery_intents(state_id)
    first = Delivery.objects.count()
    custody_alarms._ensure_delivery_intents(state_id)
    assert Delivery.objects.count() == first


@pytest.mark.parametrize(
    ("state", "age", "expected_cycle"),
    [
        (CustodyState.State.DEGRADED_ONE_RECIPIENT, timedelta(days=6), 0),
        (CustodyState.State.DEGRADED_ONE_RECIPIENT, timedelta(days=7), 1),
        (CustodyState.State.FLOOR_BREACHED_ZERO, timedelta(days=1), 1),
    ],
)
def test_reminder_cycles_follow_severity_cadence(state, age, expected_cycle):
    space = _space(f"reminder-{state}-{age.days}", state)
    _manager(space)
    _operator(f"reminder-operator-{state}-{age.days}")
    state_id = space.archive_custody_state.pk
    custody_alarms._ensure_delivery_intents(state_id)
    Delivery.objects.filter(makerspace=space).update(created_at=timezone.now() - age)

    custody_alarms._ensure_delivery_intents(state_id)

    assert Delivery.objects.filter(makerspace=space).aggregate(
        latest=Max("cycle")
    )["latest"] == expected_cycle
