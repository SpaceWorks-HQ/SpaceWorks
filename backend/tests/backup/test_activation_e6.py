import uuid
from io import StringIO

import pytest
from django.core.management import CommandError, call_command
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.backup import activation, artifact_ledger
from apps.backup.activation import (
    ActivationRecipientFloorError,
    set_superadmin_access,
)
from apps.backup.checks import check_b1_activation_integrity
from apps.backup.compound_recipients import frozen_population
from apps.backup.custody import with_makerspace_custody_lock
from apps.backup.models import (
    B1ActivationState,
    BackupArtifactComponent,
    BackupArtifactLedger,
    BackupComponentRecipient,
    MakerspaceArchiveRecipient,
)
from apps.backup.recipient_selection import BackupBuildError
from apps.makerspaces.models import Makerspace


pytestmark = pytest.mark.django_db(transaction=True)


def _recipient(makerspace, number):
    return MakerspaceArchiveRecipient.objects.create(
        makerspace=makerspace,
        public_recipient=f"age1e6recipient{makerspace.pk}{number}",
        fingerprint=f"{makerspace.pk:032x}{number:032x}",
        label=f"E6 custodian {number}",
        verified_at=timezone.now(),
    )


def _actor(username="e6-operator"):
    return User.objects.create_user(
        username=username,
        is_staff=True,
        is_superuser=True,
        access_status=User.AccessStatus.ACTIVE,
    )


def _switch(makerspace, enabled, actor):
    with with_makerspace_custody_lock(makerspace.pk) as custody:
        return set_superadmin_access(custody, enabled=enabled, actor=actor)


def test_on_to_off_pending_requires_floor_and_never_becomes_effective():
    makerspace = Makerspace.objects.create(name="E6 floor", slug="e6-floor")
    actor = _actor()
    _recipient(makerspace, 1)

    with pytest.raises(ActivationRecipientFloorError):
        _switch(makerspace, False, actor)

    makerspace.refresh_from_db()
    activation_state = B1ActivationState.objects.get(makerspace=makerspace)
    assert makerspace.superadmin_access_enabled is True
    assert activation_state.state == B1ActivationState.State.ON

    _recipient(makerspace, 2)
    _switch(makerspace, False, actor)

    makerspace.refresh_from_db()
    activation_state.refresh_from_db()
    assert makerspace.superadmin_access_enabled is False
    assert activation_state.state == B1ActivationState.State.OFF_PENDING
    assert activation_state.effective_artifact_id is None
    assert activation_state.effective_at is None


def test_switch_lock_order_is_makerspace_recipients_then_activation():
    makerspace = Makerspace.objects.create(
        name="E6 lock order",
        slug="e6-lock-order",
    )
    _recipient(makerspace, 1)
    _recipient(makerspace, 2)

    with CaptureQueriesContext(connection) as queries:
        _switch(makerspace, False, _actor())

    statements = [query["sql"] for query in queries]
    makerspace_lock = next(
        index
        for index, sql in enumerate(statements)
        if 'FROM "makerspaces_makerspace"' in sql and "FOR UPDATE" in sql
    )
    recipient_lock = next(
        index
        for index, sql in enumerate(statements)
        if 'FROM "backup_makerspacearchiverecipient"' in sql
        and "FOR UPDATE" in sql
    )
    activation_lock = next(
        index
        for index, sql in enumerate(statements)
        if 'FROM "backup_b1activationstate"' in sql and "FOR UPDATE" in sql
    )
    assert makerspace_lock < recipient_lock < activation_lock


def test_redundant_off_switch_never_demotes_off_effective():
    makerspace = Makerspace.objects.create(
        name="E6 effective",
        slug="e6-effective",
        superadmin_access_enabled=False,
    )
    artifact_id = uuid.uuid4()
    B1ActivationState.objects.filter(makerspace=makerspace).update(
        state=B1ActivationState.State.OFF_EFFECTIVE,
        effective_artifact_id=artifact_id,
        effective_at=timezone.now(),
    )

    _switch(makerspace, False, _actor())

    activation_state = B1ActivationState.objects.get(makerspace=makerspace)
    assert activation_state.state == B1ActivationState.State.OFF_EFFECTIVE
    assert activation_state.effective_artifact_id == artifact_id


def test_failed_artifact_never_advances_off_pending():
    makerspace = Makerspace.objects.create(
        name="E6 failed run",
        slug="e6-failed-run",
        superadmin_access_enabled=False,
    )
    artifact_id = uuid.uuid4()
    BackupArtifactLedger.objects.create(
        artifact_id=artifact_id,
        capture_id=uuid.uuid4(),
        archive_uuid_snapshot=uuid.uuid4(),
        outer_sha256="d" * 64,
        outer_manifest_sha256="e" * 64,
        format="spaceworks-phase5a-v3",
        outer_manifest={},
        frozen_promotion_snapshot={},
        expected_size_bytes=1,
        staging_locator=f"failed-staging/{artifact_id}",
        final_locator=f"failed-final/{artifact_id}",
    )

    artifact_ledger.mark_failed(artifact_id, "verification_failed")

    state = B1ActivationState.objects.get(makerspace=makerspace)
    assert state.state == B1ActivationState.State.OFF_PENDING
    assert state.effective_artifact_id is None


def test_reenable_changes_later_capture_only_and_preserves_prior_custody_facts():
    makerspace = Makerspace.objects.create(
        name="E6 re-enable",
        slug="e6-re-enable",
        superadmin_access_enabled=False,
    )
    recipient = _recipient(makerspace, 1)
    artifact_id = uuid.uuid4()
    ledger = BackupArtifactLedger.objects.create(
        artifact_id=artifact_id,
        capture_id=uuid.uuid4(),
        archive_uuid_snapshot=uuid.uuid4(),
        outer_sha256="a" * 64,
        outer_manifest_sha256="b" * 64,
        format="spaceworks-phase5a-v3",
        outer_manifest={},
        frozen_promotion_snapshot={},
        expected_size_bytes=13,
        staging_locator=f"staging/{artifact_id}",
        final_locator=f"final/{artifact_id}",
    )
    component = BackupArtifactComponent.objects.create(
        artifact=ledger,
        component_id=uuid.uuid4(),
        kind=BackupArtifactComponent.Kind.SLICE,
        makerspace_id_snapshot=makerspace.pk,
        ciphertext_path="slices/prior.tar.age",
        ciphertext_sha256="c" * 64,
        size_bytes=13,
    )
    association = BackupComponentRecipient.objects.create(
        component=component,
        fingerprint=recipient.fingerprint,
    )
    B1ActivationState.objects.filter(makerspace=makerspace).update(
        state=B1ActivationState.State.OFF_EFFECTIVE,
        effective_artifact_id=artifact_id,
        effective_at=timezone.now(),
    )

    _switch(makerspace, True, _actor())

    activation_state = B1ActivationState.objects.get(makerspace=makerspace)
    component.refresh_from_db()
    association.refresh_from_db()
    recipient.refresh_from_db()
    population = {item["makerspace_id"]: item for item in frozen_population()}
    assert activation_state.state == B1ActivationState.State.ON
    assert activation_state.effective_artifact_id is None
    assert population[makerspace.pk]["activation_state"] == "on"
    assert component.ciphertext_sha256 == "c" * 64
    assert association.fingerprint == recipient.fingerprint
    assert recipient.revoked_at is None
    assert recipient.compromised_at is None


def test_switch_flag_activation_audit_and_post_commit_event_are_atomic(monkeypatch):
    makerspace = Makerspace.objects.create(name="E6 atomic", slug="e6-atomic")
    actor = _actor()
    _recipient(makerspace, 1)
    _recipient(makerspace, 2)
    committed = []

    def receiver(sender, **kwargs):
        committed.append((kwargs["makerspace_id"], kwargs["enabled"]))

    def fail_audit(*args, **kwargs):
        raise RuntimeError("injected audit failure")

    activation.access_switch_committed.connect(receiver, weak=False)
    try:
        with monkeypatch.context() as scoped:
            scoped.setattr(activation.audit, "record", fail_audit)
            with pytest.raises(RuntimeError, match="audit failure"):
                _switch(makerspace, False, actor)

        makerspace.refresh_from_db()
        assert makerspace.superadmin_access_enabled is True
        assert B1ActivationState.objects.get(makerspace=makerspace).state == "on"
        assert committed == []

        _switch(makerspace, False, actor)
        assert committed == [(makerspace.pk, False)]
        assert AuditLog.objects.filter(
            makerspace=makerspace,
            action="makerspace.superadmin_access_changed",
        ).count() == 1
    finally:
        activation.access_switch_committed.disconnect(receiver)


def test_system_check_and_repair_command_detect_both_directions_and_missing_rows():
    flag_on = Makerspace.objects.create(name="Flag on", slug="e6-flag-on")
    flag_off = Makerspace.objects.create(name="Flag off", slug="e6-flag-off")
    missing = Makerspace.objects.create(name="Missing", slug="e6-missing")
    B1ActivationState.objects.filter(makerspace=flag_on).update(
        state=B1ActivationState.State.OFF_PENDING
    )
    Makerspace.objects.filter(pk=flag_off.pk).update(
        superadmin_access_enabled=False
    )
    with pytest.raises(BackupBuildError, match="flag and activation state diverge"):
        frozen_population()
    B1ActivationState.objects.filter(makerspace=missing).delete()

    errors = check_b1_activation_integrity(None)
    assert {error.id for error in errors} == {"backup.E001", "backup.E002"}
    assert str(flag_on.pk) in str(errors)
    assert str(flag_off.pk) in str(errors)
    assert str(missing.pk) in str(errors)

    output = StringIO()
    with pytest.raises(CommandError, match="3 Lane E activation integrity issue"):
        call_command("repair_b1_activation_state", dry_run=True, stdout=output)
    assert "issue=flag_state_divergence" in output.getvalue()
    assert "issue=activation_count" in output.getvalue()

    actor = _actor("e6-repair-operator")
    call_command(
        "repair_b1_activation_state",
        apply=True,
        actor_id=actor.pk,
        stdout=StringIO(),
    )
    assert check_b1_activation_integrity(None) == []
    assert B1ActivationState.objects.get(makerspace=flag_on).state == "on"
    assert B1ActivationState.objects.get(makerspace=flag_off).state == "off_pending"
    assert B1ActivationState.objects.get(makerspace=missing).state == "on"


def test_activation_system_check_is_registered_as_a_deployment_check():
    from django.core.checks import registry as checks_registry

    registered = checks_registry.registry.get_checks(include_deployment_checks=True)
    assert check_b1_activation_integrity in registered
    assert check_b1_activation_integrity(
        app_configs=None,
        databases=None,
    ) == []
