import csv
import io
import json
from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.boxes.models import Box
from apps.data_export.archive import csv_value, source_value, transform_value
from apps.data_export.datasets import DATASETS
from apps.data_export.types import Fidelity
from apps.events.models import Event, EventCollaborator, EventRegistration
from apps.hardware_requests.models import HardwareRequest
from apps.operations.models import StockTransfer
from apps.payments.models import Payment
from apps.tenant_migration.schemas import validate_snapshot
from tests.data_export.portable_helpers import (
    archive_files,
    csv_rows,
    make_job,
    make_space,
    make_user,
)
from tests.encryption.conftest import enabled_encryption

pytestmark = pytest.mark.django_db(transaction=True)


def legacy_redacted_projection(dataset, row):
    """The pre-PORTABLE writer logic, retained here as a byte regression oracle."""
    return {
        column.name: csv_value(
            transform_value(
                dataset.model,
                column.sources[0],
                column.disposition,
                source_value(row, column.sources[0]),
            )
        )
        for column in dataset.columns
    }


def create_external_rows(local, foreign, actor):
    now = timezone.now()
    event = Event.objects.create(
        makerspace=local,
        title="Shared build night",
        starts_at=now + timedelta(days=1),
        ends_at=now + timedelta(days=1, hours=2),
    )
    collaborator = EventCollaborator.objects.create(event=event, makerspace=foreign)
    registration = EventRegistration.objects.create(
        event=event,
        name="External route maker",
        email="external-route@example.test",
        phone="123",
        registered_via_makerspace=foreign,
        payment_via_makerspace=foreign,
    )
    payment = Payment.objects.create(
        makerspace=local,
        subject_type=Payment.SubjectType.EVENT_REGISTRATION,
        subject_id=registration.pk,
        via_makerspace=foreign,
        amount=Decimal("10.00"),
        currency="inr",
        created_by=actor,
    )
    local_box = Box.objects.create(makerspace=local, label="Local container")
    foreign_box = Box.objects.create(pk=900002, makerspace=foreign, label="Foreign container")
    transfer = StockTransfer.objects.create(
        makerspace=local,
        source_container=local_box,
        destination_container=foreign_box,
        source_makerspace=local,
        destination_makerspace=foreign,
        created_by=actor,
        reason="Cross-space transfer",
    )
    return collaborator, registration, transfer, payment


def test_only_genuinely_foreign_references_become_snapshots():
    """Locality is decided per row, because these columns are usually LOCAL.

    `registered_via_makerspace` is stamped `via_makerspace or locked.makerspace`, so an
    ordinary registration names the host tenant itself, and an outbound transfer's
    source is the migrating tenant. Snapshotting those would null a live reference the
    importer can remap perfectly well, and write one junk provenance row per
    registration.
    """
    actor = make_user("portable-refs-actor")
    local = make_space("portable-refs-local")
    foreign = make_space("portable-refs-foreign", pk=900001)
    with enabled_encryption():
        collaborator, registration, transfer, payment = create_external_rows(
            local, foreign, actor
        )
        local_registration = EventRegistration.objects.create(
            event=collaborator.event,
            name="Home maker",
            email="home@example.test",
            phone="456",
            registered_via_makerspace=local,
            payment_via_makerspace=local,
        )
        files, _archive_bytes, _manifest = archive_files(make_job(local, actor))

    records = [
        json.loads(line)
        for line in files["migration/external_references.jsonl"].splitlines()
    ]
    # The collaborator's EVENT is local (this tenant hosts it); the collaborating
    # MAKERSPACE is the foreign side. The transfer is outbound, so its source is local.
    assert {
        (item["source_model_label"], item["source_object_id"], item["field_name"])
        for item in records
    } == {
        ("events.EventCollaborator", str(collaborator.pk), "makerspace"),
        ("events.EventRegistration", str(registration.pk), "registered_via_makerspace"),
        ("events.EventRegistration", str(registration.pk), "payment_via_makerspace"),
        ("operations.StockTransfer", str(transfer.pk), "destination_container"),
        ("operations.StockTransfer", str(transfer.pk), "destination_makerspace"),
        ("payments.Payment", str(payment.pk), "via_makerspace"),
    }
    for item in records:
        validate_snapshot(
            item["source_model_label"], item["field_name"], item["snapshot"]
        )
        assert item["target_object_id"] not in {str(foreign.pk), "900002"}

    transfer_row = csv_rows(files, "transfers/transfers.csv")[0]
    assert transfer_row["source_makerspace_id"] == str(local.pk)
    assert transfer_row["source_container_id"] == str(transfer.source_container_id)
    assert transfer_row["destination_makerspace_id"] == ""
    assert transfer_row["destination_container_id"] == ""

    assert csv_rows(files, "events/collaborators.csv")[0]["event_id"] == str(
        collaborator.event_id
    )
    assert csv_rows(files, "payments/payments.csv")[0]["via_makerspace_id"] == ""

    by_pk = {
        row["id"]: row for row in csv_rows(files, "events/registrations.csv")
    }
    assert by_pk[str(registration.pk)]["registered_via_makerspace_id"] == ""
    # The common case: a home-space registration keeps its live, remappable id.
    assert by_pk[str(local_registration.pk)]["registered_via_makerspace_id"] == str(
        local.pk
    )
    assert by_pk[str(local_registration.pk)]["payment_via_makerspace_id"] == str(
        local.pk
    )


def test_an_inbound_collaboration_snapshots_the_foreign_event_and_anchors_locally():
    actor = make_user("inbound-refs-actor")
    local = make_space("inbound-refs-local")
    foreign = make_space("inbound-refs-foreign", pk=900003)
    now = timezone.now()
    foreign_event = Event.objects.create(
        makerspace=foreign,
        title="Their build night",
        starts_at=now + timedelta(days=2),
        ends_at=now + timedelta(days=2, hours=2),
    )
    collaborator = EventCollaborator.objects.create(
        event=foreign_event, makerspace=local
    )
    with enabled_encryption():
        files, _archive_bytes, _manifest = archive_files(make_job(local, actor))

    records = [
        json.loads(line)
        for line in files["migration/external_references.jsonl"].splitlines()
    ]
    assert [
        (item["source_object_id"], item["field_name"], item["target_model_label"])
        for item in records
    ] == [(str(collaborator.pk), "event", "events.EventCollaborator")]
    assert records[0]["snapshot"]["title"] == "Their build night"
    row = csv_rows(files, "events/collaborators.csv")[0]
    assert row["event_id"] == ""
    assert row["makerspace_id"] == str(local.pk)


def test_redacted_projection_bytes_match_the_legacy_projection_for_mapped_and_external_rows(
    monkeypatch,
):
    monkeypatch.setattr(
        "apps.data_export.external_refs.runtime_active", lambda _label: False
    )
    actor = make_user("redacted-regression-actor")
    local = make_space("redacted-regression-local")
    foreign = make_space("redacted-regression-foreign")
    request = HardwareRequest.objects.create(
        makerspace=local,
        requester=actor,
        requester_username="redacted-user",
        requester_name="Redacted fidelity keeps this readable value",
        requested_for="Regression fixture",
    )
    now = timezone.now()
    event = Event.objects.create(
        makerspace=local, title="Regression event",
        starts_at=now + timedelta(days=1), ends_at=now + timedelta(days=1, hours=1),
    )
    registration = EventRegistration.objects.create(
        event=event, name="Readable registration", email="readable@example.test",
        phone="123", registered_via_makerspace=foreign,
    )
    files, _archive_bytes, _manifest = archive_files(
        make_job(local, actor, fidelity="REDACTED")
    )
    assert csv_rows(files, "lending/requests.csv")[0]["requester_name"] == request.requester_name
    assert (
        csv_rows(files, "events/registrations.csv")[0]["registered_via_makerspace_id"]
        == str(foreign.pk)
    )

    fixtures = {
        "lending/requests.csv": request,
        "events/registrations.csv": registration,
    }
    for path, row in fixtures.items():
        dataset = DATASETS[(Fidelity.REDACTED, path)]
        expected = io.StringIO(newline="")
        writer = csv.DictWriter(
            expected, fieldnames=[column.name for column in dataset.columns]
        )
        writer.writeheader()
        writer.writerow(
            legacy_redacted_projection(dataset, type(row).objects.get(pk=row.pk))
        )
        assert files[path] == expected.getvalue().encode("utf-8")
