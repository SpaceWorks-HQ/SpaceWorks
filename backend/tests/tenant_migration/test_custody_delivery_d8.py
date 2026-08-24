import pytest

from apps.accounts.models import User
from apps.accounts.rbac import Action
from apps.backup import activation
from apps.backup.activation import set_superadmin_access
from apps.backup.custody import with_makerspace_custody_lock
from apps.backup.models import (
    B1ActivationState,
    MakerspaceTenantExitCustodyState as CustodyState,
    TenantExitCustodyAlarmDelivery as Delivery,
)
from apps.backup.recipient_states import compromise_recipient
from apps.backup.tenant_exit_custody_alarms import (
    MAX_ATTEMPTS,
    deliver_tenant_exit_custody_alarms,
    ensure_delivery_intents,
)
from apps.makerspaces.models import MakerspaceMembership, MakerspaceRole
from apps.tenant_migration.models import TenantDumpCapture
from apps.tenant_migration.tenant_dump_capture import request_tenant_dump_capture
from apps.tenant_migration.tenant_dump_errors import TenantDumpPublicationRefused
from apps.tenant_migration.tenant_dump_publication import publish_tenant_dump
from tests.tenant_migration.tenant_dump_d3_helpers import makerspace, manager, operator, recipient


pytestmark = pytest.mark.django_db
def _member(space, suffix, *, actions=(), operator_role=False, active=True):
    role = MakerspaceRole.objects.create(
        makerspace=space,
        name=f"D8 {suffix}",
        slug=f"d8-{suffix}",
        granted_actions=list(actions),
    )
    user = User.objects.create_user(
        username=f"{space.slug}-{suffix}",
        email=f"{space.slug}-{suffix}@example.test",
        role=User.Role.SUPERADMIN if operator_role else User.Role.REQUESTER,
        is_superuser=operator_role,
        access_status=User.AccessStatus.ACTIVE,
    )
    MakerspaceMembership.objects.create(
        makerspace=space,
        user=user,
        role=MakerspaceMembership.Role.CUSTOM,
        assigned_role=role,
        status="active" if active else "revoked",
    )
    return user


@pytest.fixture
def _no_external_anchor(monkeypatch):
    monkeypatch.setattr("apps.tenant_migration.tenant_dump_publication.prove_no_external_anchor", lambda _id: True)


def test_decision_19b_selects_only_active_non_operator_manage_makerspace_members():
    space = makerspace("d8-recipient-authority")
    eligible = _member(space, "eligible", actions=(Action.MANAGE_MAKERSPACE,))
    _member(space, "no-authority")
    _member(space, "inactive", actions=(Action.MANAGE_MAKERSPACE,), active=False)
    platform = _member(
        space,
        "platform-operator",
        actions=(Action.MANAGE_MAKERSPACE,),
        operator_role=True,
    )
    state = CustodyState.objects.create(
        makerspace=space,
        state=CustodyState.State.DEGRADED_ONE_RECIPIENT,
        alarm_episode=1,
        alarm_revision=1,
    )

    ensure_delivery_intents(state.pk)

    targeted = set(
        Delivery.objects.filter(makerspace=space).exclude(recipient_ref=None).values_list(
            "channel", "recipient_ref"
        )
    )
    assert targeted == {(Delivery.Channel.TENANT_EMAIL, eligible.pk)}
    assert (Delivery.Channel.OPERATOR_EMAIL, platform.pk) not in targeted


@pytest.mark.parametrize(
    "space_enabled,opted_in,expected",
    (
        (False, True, {Delivery.Channel.TENANT_INAPP, Delivery.Channel.OPERATOR_EMAIL}),
        (True, False, {Delivery.Channel.TENANT_INAPP, Delivery.Channel.OPERATOR_EMAIL}),
    ),
)
def test_decision_19b_email_disable_or_opt_out_falls_back_to_operator(
    space_enabled, opted_in, expected):
    space = makerspace(f"d8-routing-{space_enabled}-{opted_in}")
    space.staff_notifications_enabled = space_enabled
    space.save(update_fields=("staff_notifications_enabled", "updated_at"))
    manager(space, opted_in=opted_in)
    operator(f"d8-routing-operator-{space_enabled}-{opted_in}")
    state = CustodyState.objects.create(
        makerspace=space,
        state=CustodyState.State.DEGRADED_ONE_RECIPIENT,
        alarm_episode=1,
        alarm_revision=1,
    )

    ensure_delivery_intents(state.pk)

    assert set(Delivery.objects.filter(makerspace=space).values_list("channel", flat=True)) == expected


def test_notifications_module_disabled_removes_only_tenant_inapp_intent():
    space = makerspace("d8-routing-module-disabled", modules=())
    tenant = manager(space)
    state = CustodyState.objects.create(
        makerspace=space,
        state=CustodyState.State.DEGRADED_ONE_RECIPIENT,
        alarm_episode=1,
        alarm_revision=1,
    )

    ensure_delivery_intents(state.pk)

    assert set(Delivery.objects.filter(makerspace=space).values_list(
        "channel", "recipient_ref")) == {(Delivery.Channel.TENANT_EMAIL, tenant.pk)}


def test_exhausted_tenant_delivery_is_escalated_on_a_later_sweep(monkeypatch):
    space = makerspace("d8-exhausted-escalation")
    tenant = manager(space)
    platform = operator("d8-exhausted-escalation-operator")
    state = CustodyState.objects.create(
        makerspace=space,
        state=CustodyState.State.DEGRADED_ONE_RECIPIENT,
        alarm_episode=1,
        alarm_revision=1,
    )
    ensure_delivery_intents(state.pk)
    Delivery.objects.filter(
        makerspace=space,
        channel=Delivery.Channel.TENANT_EMAIL,
        recipient_ref=tenant.pk,
    ).update(status=Delivery.Status.EXHAUSTED, attempts=MAX_ATTEMPTS)
    monkeypatch.setattr(
        "apps.backup.tenant_exit_custody_alarms.deliver_claimable_rows",
        lambda **_kwargs: 0,
    )

    deliver_tenant_exit_custody_alarms(makerspace_id=space.pk)

    assert Delivery.objects.filter(
        makerspace=space,
        alarm_revision=state.alarm_revision,
        channel=Delivery.Channel.OPERATOR_EMAIL,
        recipient_ref=platform.pk,
    ).exists()


def test_enqueue_failure_cannot_roll_back_recipient_or_custody_state(
    monkeypatch, django_capture_on_commit_callbacks
):
    space = makerspace("d8-enqueue-recipient")
    manager(space)
    first = recipient(space, 61)
    recipient(space, 62)
    monkeypatch.setattr(
        "apps.backup.tasks.deliver_tenant_exit_custody_alarms_task.delay",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("queue unavailable")),
    )

    with django_capture_on_commit_callbacks(execute=True):
        compromise_recipient(recipient=first)

    first.refresh_from_db()
    state = CustodyState.objects.get(makerspace=space)
    assert first.compromised_at is not None
    assert state.state == CustodyState.State.DEGRADED_ONE_RECIPIENT
    assert Delivery.objects.filter(
        makerspace=space, alarm_revision=state.alarm_revision
    ).exists()


@pytest.mark.xfail(strict=True, reason="SPEC BUG: backend/apps/backup/activation.py:83 registers a functools.partial as a robust on_commit callback, so a receiver failure escapes through Django's missing __qualname__ error path.")
def test_post_commit_failure_cannot_roll_back_activation(
    django_capture_on_commit_callbacks
):
    space = makerspace("d8-activation-callback")
    actor = operator("d8-activation-callback-operator")
    recipient(space, 63)
    recipient(space, 64)

    def fail_receiver(**_kwargs):
        raise RuntimeError("subscriber unavailable")

    activation.access_switch_committed.connect(fail_receiver, weak=False)
    try:
        with django_capture_on_commit_callbacks(execute=True):
            with with_makerspace_custody_lock(space.pk) as custody:
                set_superadmin_access(custody, enabled=False, actor=actor)
    finally:
        activation.access_switch_committed.disconnect(fail_receiver)

    space.refresh_from_db()
    assert space.superadmin_access_enabled is False
    assert B1ActivationState.objects.get(makerspace=space).state == B1ActivationState.State.OFF_PENDING


def test_post_commit_cleanup_failure_cannot_roll_back_publication(
    monkeypatch, django_capture_on_commit_callbacks, _no_external_anchor
):
    space = makerspace("d8-publication-callback")
    actor = manager(space)
    recipient(space, 65)
    recipient(space, 66)
    capture = request_tenant_dump_capture(actor, space)
    capture.status = TenantDumpCapture.Status.PENDING_PUBLICATION
    capture.unpublished_object_key = f"tenant-dumps/unpublished/{capture.pk}.age"
    capture.artifact_sha256 = "a" * 64
    capture.artifact_size_bytes = 1
    capture.save()
    monkeypatch.setattr(
        "apps.tenant_migration.tenant_dump_publication._verify_publication_lineage",
        lambda _capture: None,
    )
    monkeypatch.setattr(
        "apps.tenant_migration.tenant_dump_publication._delete_capture_staging",
        lambda _capture_id: (_ for _ in ()).throw(RuntimeError("cleanup unavailable")),
    )

    with django_capture_on_commit_callbacks(execute=True):
        published, token = publish_tenant_dump(capture.pk)

    published.refresh_from_db()
    assert token
    assert published.status == TenantDumpCapture.Status.PUBLISHED
    assert published.object_key.endswith(".age")


def test_zero_recipient_boundary_blocks_publication_and_creates_no_download_state(
    monkeypatch, _no_external_anchor
):
    space = makerspace("d8-zero-publication")
    actor = manager(space)
    sole_recipient = recipient(space, 67)
    capture = request_tenant_dump_capture(actor, space)
    capture.status = TenantDumpCapture.Status.PENDING_PUBLICATION
    capture.unpublished_object_key = f"tenant-dumps/unpublished/{capture.pk}.age"
    capture.artifact_sha256 = "b" * 64
    capture.artifact_size_bytes = 1
    capture.save()
    compromise_recipient(recipient=sole_recipient)
    monkeypatch.setattr(
        "apps.tenant_migration.tenant_dump_publication._delete_unpublished",
        lambda *_args: None,
    )

    with pytest.raises(TenantDumpPublicationRefused, match="zero|changed"):
        publish_tenant_dump(capture.pk)

    capture.refresh_from_db()
    assert capture.status == TenantDumpCapture.Status.REFUSED
    assert capture.object_key == ""
    assert capture.download_token_digest == ""
    assert capture.download_token_expires_at is None


def test_recipient_mutation_after_publication_does_not_revoke_published_artifact(
    monkeypatch, _no_external_anchor
):
    space = makerspace("d8-post-publication-recipient")
    actor = manager(space)
    first = recipient(space, 68)
    recipient(space, 69)
    capture = request_tenant_dump_capture(actor, space)
    capture.status = TenantDumpCapture.Status.PENDING_PUBLICATION
    capture.unpublished_object_key = f"tenant-dumps/unpublished/{capture.pk}.age"
    capture.artifact_sha256 = "c" * 64
    capture.artifact_size_bytes = 1
    capture.save()
    monkeypatch.setattr(
        "apps.tenant_migration.tenant_dump_publication._verify_publication_lineage",
        lambda _capture: None,
    )

    published, _token = publish_tenant_dump(capture.pk)
    committed_state = (
        published.status,
        published.object_key,
        published.download_token_digest,
        published.download_token_expires_at,
    )
    compromise_recipient(recipient=first)
    published.refresh_from_db()

    assert (
        published.status,
        published.object_key,
        published.download_token_digest,
        published.download_token_expires_at,
    ) == committed_state
