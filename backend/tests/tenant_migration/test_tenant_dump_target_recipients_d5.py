from datetime import timedelta

import pytest
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.backup.models import (
    ArchiveCustodyAlarmDelivery,
    ArchiveRecipientReservation,
    MakerspaceArchiveCustodyState,
    MakerspaceArchiveRecipient,
    MakerspaceTenantExitCustodyState,
    TenantExitCustodyAlarmDelivery,
)
from apps.backup.recipients import (
    encode_unpadded_base64url,
    fingerprint_for,
    nonce_digest,
)
from apps.tenant_migration.tenant_dump_errors import TenantDumpTargetError
from apps.tenant_migration.tenant_dump_raw import sanitize_record
from apps.tenant_migration.tenant_dump_target_custody import (
    assert_imported_part_a_operational_rows_absent,
    prove_imported_tenant_recipients,
)
from tests.tenant_migration.tenant_dump_d3_helpers import operator
from tests.tenant_migration.tenant_dump_d5_helpers import (
    age_recipient,
    importing_space,
    target_identity,
)


pytestmark = pytest.mark.django_db
GOOD_NONCE = b"n" * 32
BAD_NONCE = b"x" * 32


def _carried_recipient(space, seed=11, **overrides):
    public = age_recipient(seed)
    values = {
        "makerspace": space,
        "public_recipient": public,
        "fingerprint": fingerprint_for(public),
        "label": f"Carried {seed}",
    }
    values.update(overrides)
    return MakerspaceArchiveRecipient.objects.create(**values)


def test_lane_d_projection_preserves_public_metadata_but_clears_source_proof():
    space = importing_space("d5-recipient-projection")
    source_verified_at = timezone.now() - timedelta(days=30)
    recipient = _carried_recipient(
        space,
        verified_at=source_verified_at,
        challenge_nonce_digest="a" * 64,
        challenge_issued_at=source_verified_at - timedelta(minutes=1),
    )
    source = {
        field.attname: field.value_from_object(recipient)
        for field in MakerspaceArchiveRecipient._meta.concrete_fields
    }

    projected = sanitize_record(MakerspaceArchiveRecipient, source).values

    assert projected["public_recipient"] == recipient.public_recipient
    assert projected["fingerprint"] == recipient.fingerprint
    assert projected["label"] == recipient.label
    assert projected["verified_at"] is None
    assert projected["challenge_nonce_digest"] == ""
    assert projected["challenge_issued_at"] is None


@pytest.mark.parametrize(
    "operational_row",
    (
        "reservation",
        "archive_state",
        "tenant_exit_state",
        "archive_outbox",
        "tenant_exit_outbox",
    ),
)
def test_any_imported_operational_custody_row_is_refused(operational_row):
    space = importing_space(f"d5-imported-{operational_row}")
    recipient = _carried_recipient(space)
    if operational_row == "reservation":
        ArchiveRecipientReservation.objects.create(
            fingerprint=recipient.fingerprint,
            makerspace_id_snapshot=space.pk,
            kind=ArchiveRecipientReservation.Kind.TENANT,
        )
    elif operational_row == "archive_state":
        MakerspaceArchiveCustodyState.objects.create(makerspace=space)
    elif operational_row == "tenant_exit_state":
        MakerspaceTenantExitCustodyState.objects.create(makerspace=space)
    elif operational_row == "archive_outbox":
        ArchiveCustodyAlarmDelivery.objects.create(
            makerspace=space,
            alarm_revision=1,
            channel=ArchiveCustodyAlarmDelivery.Channel.TENANT_INAPP,
        )
    else:
        TenantExitCustodyAlarmDelivery.objects.create(
            makerspace=space,
            alarm_revision=1,
            channel=TenantExitCustodyAlarmDelivery.Channel.TENANT_INAPP,
        )

    with pytest.raises(TenantDumpTargetError) as caught:
        assert_imported_part_a_operational_rows_absent(space.pk)

    assert caught.value.code == "source_custody_state_present"


@pytest.mark.parametrize(
    "proof_field", ("verified_at", "challenge_nonce_digest", "challenge_issued_at")
)
def test_source_recipient_proof_state_is_never_trusted(proof_field):
    space = importing_space(f"d5-source-proof-{proof_field.replace('_', '-')}")
    value = "a" * 64 if proof_field == "challenge_nonce_digest" else timezone.now()
    recipient = _carried_recipient(space, **{proof_field: value})

    with pytest.raises(TenantDumpTargetError) as caught:
        assert_imported_part_a_operational_rows_absent(space.pk)

    recipient.refresh_from_db()
    assert caught.value.code == "source_recipient_proof_present"
    assert getattr(recipient, proof_field) == value
    assert not ArchiveRecipientReservation.objects.filter(
        fingerprint=recipient.fingerprint
    ).exists()


def _target_challenge(monkeypatch, *, submitted_nonce):
    def reissue(*, recipient, actor=None):
        recipient.challenge_nonce_digest = nonce_digest(GOOD_NONCE)
        recipient.challenge_issued_at = timezone.now()
        recipient.save(
            update_fields=("challenge_nonce_digest", "challenge_issued_at")
        )
        return recipient, "opaque-target-challenge"

    monkeypatch.setattr(
        "apps.tenant_migration.tenant_dump_target_custody.reissue_recipient_challenge",
        reissue,
    )
    monkeypatch.setattr(
        "apps.tenant_migration.tenant_dump_target_custody.decrypt_target_recipient_challenge",
        lambda _identity, _challenge: encode_unpadded_base64url(submitted_nonce),
    )


def test_only_passing_target_challenge_verifies_and_reserves_matching_recipient(
    monkeypatch,
):
    space = importing_space("d5-target-proof-pass")
    matching = _carried_recipient(space, 11)
    unrelated = _carried_recipient(space, 12)
    operator("d5-target-proof-pass-operator")
    _target_challenge(monkeypatch, submitted_nonce=GOOD_NONCE)
    before = timezone.now()

    proven = prove_imported_tenant_recipients(
        space.pk,
        (target_identity("/mounted/tenant.agekey", 11),),
    )

    matching.refresh_from_db()
    unrelated.refresh_from_db()
    assert proven == (matching.pk,)
    assert matching.verified_at is not None and matching.verified_at >= before
    assert matching.challenge_nonce_digest == ""
    assert unrelated.verified_at is None
    assert ArchiveRecipientReservation.objects.filter(
        fingerprint=matching.fingerprint,
        makerspace_id_snapshot=space.pk,
        kind=ArchiveRecipientReservation.Kind.TENANT,
    ).exists()
    assert not ArchiveRecipientReservation.objects.filter(
        fingerprint=unrelated.fingerprint
    ).exists()
    assert AuditLog.objects.filter(
        makerspace=space,
        target_id=str(matching.pk),
        action="tenant_migration.target_archive_recipient_verified",
    ).exists()


def test_failed_target_challenge_creates_no_verification_audit_or_reservation(
    monkeypatch,
):
    space = importing_space("d5-target-proof-fail")
    recipient = _carried_recipient(space, 11)
    _target_challenge(monkeypatch, submitted_nonce=BAD_NONCE)

    with pytest.raises(TenantDumpTargetError) as caught:
        prove_imported_tenant_recipients(
            space.pk,
            (target_identity("/mounted/tenant.agekey", 11),),
        )

    recipient.refresh_from_db()
    assert caught.value.code == "recipient_challenge_failed"
    assert recipient.verified_at is None
    assert not ArchiveRecipientReservation.objects.filter(
        fingerprint=recipient.fingerprint
    ).exists()
    assert not AuditLog.objects.filter(
        makerspace=space,
        action="tenant_migration.target_archive_recipient_verified",
    ).exists()
