import json
from datetime import timedelta
from decimal import Decimal

import pytest
from django.db import transaction
from django.utils import timezone

from apps.accounts.models_claim import MemberClaimCode
from apps.boxes.models import QrCode
from apps.boxes.rebind import rebind_qr_target
from apps.data_export.errors import ExportIntegrityError
from apps.events.models import Event, EventRegistration
from apps.inventory.models import InventoryProduct
from apps.makerspaces.models import MakerspaceMembership
from apps.notifications.models import Notification
from apps.operations.models import QrPrintBatch
from apps.operations.services_qr_assets import add_qr_to_batch
from apps.payments.models import Payment
from apps.presence.models import PresenceSession
from tests.data_export.portable_helpers import (
    archive_files,
    csv_rows,
    make_job,
    make_space,
    make_user,
)
from tests.encryption.conftest import enabled_encryption

pytestmark = pytest.mark.django_db(transaction=True)


def provenance(files):
    return [
        json.loads(line)
        for line in files["migration/reference_provenance.jsonl"].splitlines()
    ]


def product(makerspace, name):
    return InventoryProduct.objects.create(
        makerspace=makerspace,
        name=name,
        total_quantity=1,
        available_quantity=1,
    )


def test_undeclared_discriminator_fails_before_it_reaches_archive():
    actor = make_user("portable-invalid-discriminator")
    makerspace = make_space("portable-invalid-discriminator")
    qr = QrCode.objects.create(
        makerspace=makerspace,
        target_type="future_target",
        target_id=987654,
        created_by=actor,
    )

    with pytest.raises(
        ExportIntegrityError,
        match=rf"boxes\.QrCode row {qr.pk}.*future_target",
    ):
        archive_files(make_job(makerspace, actor))


def test_print_batch_item_keeps_its_snapshot_after_qr_rebind():
    actor = make_user("portable-batch-rebind")
    makerspace = make_space("portable-batch-rebind")
    MakerspaceMembership.objects.create(
        makerspace=makerspace,
        user=actor,
        role=MakerspaceMembership.Role.INVENTORY_MANAGER,
    )
    original = product(makerspace, "Original drill")
    replacement = product(makerspace, "Replacement drill")
    qr = QrCode.objects.create(
        makerspace=makerspace,
        target_type=QrCode.TargetType.PRODUCT,
        target_id=original.pk,
        created_by=actor,
    )
    batch = QrPrintBatch.objects.create(
        makerspace=makerspace,
        title="Printed labels",
        created_by=actor,
    )
    item = add_qr_to_batch(batch, qr)

    with transaction.atomic():
        rebind_qr_target(
            actor,
            qr.pk,
            {"target_type": QrCode.TargetType.PRODUCT, "target_id": replacement.pk},
        )
    files, _archive_bytes, _manifest = archive_files(make_job(makerspace, actor))

    qr_row = csv_rows(files, "inventory/qr_mappings.csv")[0]
    item_row = csv_rows(files, "operations/qr_print_batch_items.csv")[0]
    assert qr_row["target_id"] == str(replacement.pk)
    assert item_row["target_type"] == QrCode.TargetType.PRODUCT
    assert item_row["target_id"] == str(original.pk)
    assert item_row["label_text"] == item.label_text


def test_claim_created_presence_is_nulled_with_typed_provenance():
    actor = make_user("portable-presence")
    makerspace = make_space("portable-presence")
    membership = MakerspaceMembership.objects.create(
        makerspace=makerspace,
        user=actor,
        role=MakerspaceMembership.Role.INVENTORY_MANAGER,
    )
    now = timezone.now()
    claim = MemberClaimCode.objects.create(
        membership=membership,
        code_digest="a" * 64,
        issued_by=actor,
        expires_at=now + timedelta(hours=1),
    )
    session = PresenceSession.objects.create(
        member=actor,
        makerspace=makerspace,
        membership=membership,
        created_via_claim_session=claim,
        started_at=now,
        expires_at=now + timedelta(minutes=30),
    )

    files, _archive_bytes, _manifest = archive_files(make_job(makerspace, actor))

    assert csv_rows(files, "presence/sessions.csv")[0][
        "created_via_claim_session_id"
    ] == ""
    assert provenance(files) == [
        {
            "source_model_label": "presence.PresenceSession",
            "source_object_id": str(session.pk),
            "field_name": "created_via_claim_session",
            "kind": "omitted_target_model",
            "detail": {
                "source_target_id": str(claim.pk),
                "target_model_label": "accounts.MemberClaimCode",
            },
        }
    ]


def test_only_absent_payment_subject_is_marked_orphaned():
    actor = make_user("portable-payment-subject")
    makerspace = make_space("portable-payment-subject")
    now = timezone.now()
    with enabled_encryption():
        event = Event.objects.create(
            makerspace=makerspace,
            title="Paid workshop",
            starts_at=now + timedelta(days=1),
            ends_at=now + timedelta(days=1, hours=1),
        )
        present = EventRegistration.objects.create(
            event=event,
            name="Present subject",
            email="present@example.test",
            phone="1",
        )
        removed = EventRegistration.objects.create(
            event=event,
            name="Removed subject",
            email="removed@example.test",
            phone="2",
        )
        Payment.objects.create(
            makerspace=makerspace,
            subject_type=Payment.SubjectType.EVENT_REGISTRATION,
            subject_id=present.pk,
            subject_label="Present registration",
            amount=Decimal("10.00"),
            currency="inr",
            created_by=actor,
        )
        orphan = Payment.objects.create(
            makerspace=makerspace,
            subject_type=Payment.SubjectType.EVENT_REGISTRATION,
            subject_id=removed.pk,
            subject_label="Preserved workshop receipt",
            amount=Decimal("11.00"),
            currency="inr",
            created_by=actor,
        )
        removed_id = removed.pk
        removed.delete()

        files, _archive_bytes, _manifest = archive_files(make_job(makerspace, actor))

    records = [row for row in provenance(files) if row["kind"] == "orphaned_payment_subject"]
    assert records == [
        {
            "source_model_label": "payments.Payment",
            "source_object_id": str(orphan.pk),
            "field_name": "subject_id",
            "kind": "orphaned_payment_subject",
            "detail": {
                "source_target_id": str(removed_id),
                "subject_label": "Preserved workshop receipt",
                "subject_type": Payment.SubjectType.EVENT_REGISTRATION,
                "target_model_label": "events.EventRegistration",
            },
        }
    ]


def test_unrecognised_notification_url_is_provenance_but_not_rewritten():
    actor = make_user("portable-notification-url")
    makerspace = make_space("portable-notification-url")
    unknown = Notification.objects.create(
        makerspace=makerspace,
        title="Old route",
        url_path="/admin/future-model/77",
    )

    files, _archive_bytes, _manifest = archive_files(make_job(makerspace, actor))

    row = csv_rows(files, "notifications/inbox.csv")[0]
    assert row["url_path"] == unknown.url_path
    assert provenance(files) == [
        {
            "source_model_label": "notifications.Notification",
            "source_object_id": str(unknown.pk),
            "field_name": "url_path",
            "kind": "unrecognised_notification_url",
            "detail": {"source_url_path": unknown.url_path},
        }
    ]
