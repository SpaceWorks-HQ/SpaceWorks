import pytest
from django.utils import timezone

from apps.backup.custody_alarm_dispatch import CLAIM_LEASE, deliver_claimable_rows
from apps.backup.models import (
    MakerspaceTenantExitCustodyState as CustodyState,
    TenantExitCustodyAlarmDelivery as Delivery,
)
from apps.backup.tenant_exit_custody_alarms import (
    deliver_tenant_exit_custody_alarms,
)
from apps.integrations.models import EmailLog
from apps.tenant_migration.tenant_dump_capture import request_tenant_dump_capture
from apps.tenant_migration.tenant_dump_errors import TenantDumpCustodyError
from tests.tenant_migration.tenant_dump_d3_helpers import (
    makerspace,
    manager,
    operator,
    recipient,
)


pytestmark = pytest.mark.django_db


def _channels(space):
    return set(
        Delivery.objects.filter(makerspace=space).values_list("channel", flat=True)
    )


def _sent_dispatch(**kwargs):
    return EmailLog.objects.create(
        makerspace=kwargs["makerspace"],
        to_email=kwargs["to_email"],
        subject=kwargs["subject"],
        text_body=kwargs["text_body"],
        stream=kwargs["stream"],
        event=kwargs["event"],
        audience=kwargs["audience"],
        connection_kind=kwargs["connection"],
        status=EmailLog.Status.SENT,
        sent_at=timezone.now(),
    )


def test_decision_19b_is_tenant_first_for_degraded_episode():
    space = makerspace("d3-tenant-first")
    actor = manager(space)
    operator("d3-tenant-first-operator")
    recipient(space, 30)

    request_tenant_dump_capture(actor, space)

    assert _channels(space) == {
        Delivery.Channel.TENANT_INAPP,
        Delivery.Channel.TENANT_EMAIL,
    }


def test_decision_19b_sends_operators_every_zero_revision():
    space = makerspace("d3-zero-operator")
    actor = manager(space)
    platform = operator("d3-floor-operator")

    with pytest.raises(TenantDumpCustodyError):
        request_tenant_dump_capture(actor, space)

    state = CustodyState.objects.get(makerspace=space)
    assert Delivery.objects.filter(
        makerspace=space,
        alarm_revision=state.alarm_revision,
        channel=Delivery.Channel.OPERATOR_EMAIL,
        recipient_ref=platform.pk,
    ).exists()


def test_resolve_time_fallback_uses_operator_when_tenant_is_not_mailable():
    space = makerspace("d3-unmailable", modules=())
    actor = manager(space, mailable=False)
    platform = operator("d3-unmailable-operator")
    recipient(space, 31)

    request_tenant_dump_capture(actor, space)

    assert _channels(space) == {Delivery.Channel.OPERATOR_EMAIL}
    assert Delivery.objects.filter(recipient_ref=platform.pk).exists()


def test_outbound_failure_does_not_roll_back_custody(monkeypatch):
    space = makerspace("d3-outbound-failure", modules=())
    actor = manager(space)
    recipient(space, 32)
    request_tenant_dump_capture(actor, space)

    def failed(**kwargs):
        log = _sent_dispatch(**kwargs)
        log.status = EmailLog.Status.FAILED
        log.error = "provider unavailable"
        log.save(update_fields=("status", "error"))
        return log

    monkeypatch.setattr("apps.backup.custody_alarm_dispatch.dispatch_email", failed)
    deliver_tenant_exit_custody_alarms(makerspace_id=space.pk)

    state = CustodyState.objects.get(makerspace=space)
    delivery = Delivery.objects.get(
        makerspace=space,
        channel=Delivery.Channel.TENANT_EMAIL,
    )
    assert state.state == CustodyState.State.DEGRADED_ONE_RECIPIENT
    assert delivery.status == Delivery.Status.FAILED
    assert delivery.attempts == 1


def test_worker_death_after_send_can_duplicate_but_cannot_drop(monkeypatch):
    space = makerspace("d3-at-least-once", modules=())
    user = manager(space)
    state = CustodyState.objects.create(
        makerspace=space,
        state=CustodyState.State.DEGRADED_ONE_RECIPIENT,
        alarm_episode=1,
        alarm_revision=1,
    )
    row = Delivery.objects.create(
        makerspace=space,
        alarm_revision=state.alarm_revision,
        channel=Delivery.Channel.TENANT_EMAIL,
        recipient_user=user,
        recipient_ref=user.pk,
    )
    accepted = []

    def transport(**kwargs):
        accepted.append(kwargs["to_email"])
        if len(accepted) == 1:
            raise SystemExit("worker died after acceptance")
        return _sent_dispatch(**kwargs)

    monkeypatch.setattr("apps.backup.custody_alarm_dispatch.dispatch_email", transport)
    with pytest.raises(SystemExit):
        deliver_claimable_rows(
            makerspace_id=space.pk,
            limit=1,
            delivery_model=Delivery,
            state_model=CustodyState,
            event="tenant_exit_custody_alarm",
            custody_label="Tenant exit",
        )
    Delivery.objects.filter(pk=row.pk).update(
        claimed_at=timezone.now() - CLAIM_LEASE
    )

    deliver_claimable_rows(
        makerspace_id=space.pk,
        limit=1,
        delivery_model=Delivery,
        state_model=CustodyState,
        event="tenant_exit_custody_alarm",
        custody_label="Tenant exit",
    )

    row.refresh_from_db()
    assert accepted == [user.email, user.email]
    assert row.status == Delivery.Status.SENT
