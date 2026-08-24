import pytest
from django.utils import timezone

from apps.backup.models import (
    ArchiveRecipientReservation,
    MakerspaceArchiveCustodyState,
    MakerspaceArchiveRecipient,
    MakerspaceTenantExitCustodyState,
    TenantExitCustodyAlarmDelivery,
)
from apps.backup.recipients import fingerprint_for
from apps.backup.tenant_exit_custody_alarms import (
    required_intents_present_locked,
)
from apps.tenant_migration.tenant_dump_errors import TenantDumpTargetError
from apps.tenant_migration.tenant_dump_target_custody import (
    reroute_target_custody,
    target_custody_readiness,
)
from tests.tenant_migration.tenant_dump_d3_helpers import manager, operator
from tests.tenant_migration.tenant_dump_d5_helpers import (
    age_recipient,
    importing_space,
)


pytestmark = pytest.mark.django_db


def _verified_recipient(space, seed):
    public = age_recipient(seed)
    recipient = MakerspaceArchiveRecipient.objects.create(
        makerspace=space,
        public_recipient=public,
        fingerprint=fingerprint_for(public),
        label=f"Target custodian {seed}",
        verified_at=timezone.now(),
    )
    ArchiveRecipientReservation.objects.create(
        fingerprint=recipient.fingerprint,
        makerspace_id_snapshot=space.pk,
        kind=ArchiveRecipientReservation.Kind.TENANT,
    )
    return recipient


def test_zero_tenant_recipients_derives_independent_states_and_refuses_readiness():
    space = importing_space("d5-custody-zero")
    operator("d5-custody-zero-operator")

    with pytest.raises(TenantDumpTargetError) as caught:
        target_custody_readiness(space.pk)

    archive = MakerspaceArchiveCustodyState.objects.get(makerspace=space)
    tenant_exit = MakerspaceTenantExitCustodyState.objects.get(makerspace=space)
    assert caught.value.code == "tenant_custody_zero"
    assert archive.state == archive.State.NOT_APPLICABLE
    assert tenant_exit.state == tenant_exit.State.FLOOR_BREACHED_ZERO
    assert tenant_exit.alarm_revision > 0


@pytest.mark.parametrize(
    "forged",
    (
        MakerspaceArchiveCustodyState.State.DEGRADED_ONE_RECIPIENT,
        MakerspaceArchiveCustodyState.State.FLOOR_BREACHED_ZERO,
        MakerspaceArchiveCustodyState.State.HEALTHY,
    ),
)
def test_part_a_custody_cannot_be_forged_while_superadmin_access_is_enabled(forged):
    space = importing_space(f"d5-forged-{forged}")
    _verified_recipient(space, 21)
    MakerspaceArchiveCustodyState.objects.create(makerspace=space, state=forged)
    MakerspaceTenantExitCustodyState.objects.create(
        makerspace=space,
        state=MakerspaceTenantExitCustodyState.State.DEGRADED_ONE_RECIPIENT,
        alarm_revision=1,
    )

    with pytest.raises(TenantDumpTargetError) as caught:
        target_custody_readiness(space.pk, recompute=False)

    assert caught.value.code == "archive_custody_forged"


def test_one_recipient_requires_positive_degraded_revision_and_durable_intents():
    space = importing_space("d5-custody-one")
    _verified_recipient(space, 22)
    MakerspaceArchiveCustodyState.objects.create(
        makerspace=space,
        state=MakerspaceArchiveCustodyState.State.NOT_APPLICABLE,
    )
    state = MakerspaceTenantExitCustodyState.objects.create(
        makerspace=space,
        state=MakerspaceTenantExitCustodyState.State.DEGRADED_ONE_RECIPIENT,
        alarm_revision=0,
    )

    with pytest.raises(TenantDumpTargetError) as caught:
        target_custody_readiness(space.pk, recompute=False)
    assert caught.value.code == "tenant_custody_degraded_unready"

    platform = operator("d5-custody-one-operator")
    readiness = reroute_target_custody(space.pk)
    state.refresh_from_db()

    assert readiness.verified_recipient_count == 1
    assert readiness.archive_state == MakerspaceArchiveCustodyState.State.NOT_APPLICABLE
    assert readiness.tenant_exit_state == state.State.DEGRADED_ONE_RECIPIENT
    assert state.alarm_revision > 0
    assert required_intents_present_locked(state)
    assert TenantExitCustodyAlarmDelivery.objects.filter(
        makerspace=space,
        alarm_revision=state.alarm_revision,
        channel=TenantExitCustodyAlarmDelivery.Channel.OPERATOR_EMAIL,
        recipient_ref=platform.pk,
    ).exists()


def test_two_recipients_are_healthy_independently_of_part_a_not_applicable():
    space = importing_space("d5-custody-two")
    _verified_recipient(space, 23)
    _verified_recipient(space, 24)

    readiness = reroute_target_custody(space.pk)

    assert readiness.verified_recipient_count == 2
    assert readiness.archive_state == MakerspaceArchiveCustodyState.State.NOT_APPLICABLE
    assert readiness.tenant_exit_state == MakerspaceTenantExitCustodyState.State.HEALTHY


@pytest.mark.parametrize("tenant_staff", ("missing", "unmailable"))
def test_resolve_time_routing_reruns_after_target_superadmin_exists(tenant_staff):
    space = importing_space(f"d5-reroute-{tenant_staff}")
    _verified_recipient(space, 30 if tenant_staff == "missing" else 31)
    if tenant_staff == "unmailable":
        manager(space, suffix="unmailable", mailable=False)

    with pytest.raises(TenantDumpTargetError) as before_operator:
        reroute_target_custody(space.pk)
    assert before_operator.value.code == "tenant_custody_degraded_unready"
    state = MakerspaceTenantExitCustodyState.objects.get(makerspace=space)
    assert state.alarm_revision > 0
    assert not TenantExitCustodyAlarmDelivery.objects.filter(
        makerspace=space,
        alarm_revision=state.alarm_revision,
        channel=TenantExitCustodyAlarmDelivery.Channel.OPERATOR_EMAIL,
    ).exists()

    platform = operator(f"d5-reroute-{tenant_staff}-operator")
    readiness = target_custody_readiness(space.pk, recompute=True)
    state.refresh_from_db()

    assert readiness.verified_recipient_count == 1
    assert required_intents_present_locked(state)
    assert TenantExitCustodyAlarmDelivery.objects.filter(
        makerspace=space,
        alarm_revision=state.alarm_revision,
        channel=TenantExitCustodyAlarmDelivery.Channel.OPERATOR_EMAIL,
        recipient_ref=platform.pk,
    ).exists()
