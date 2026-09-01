import json
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.bookings.models import BookableSpace, Booking
from apps.data_export.pii_raw import aad_inputs, mapped_field_names
from apps.data_export.runner import ExportIntegrityError
from apps.encryption.crypto import is_envelope
from apps.events.models import Event, EventRegistration
from apps.hardware_requests.models import HardwareRequest
from apps.machines.models import (
    Machine,
    MachineServiceRequest,
    MachineType,
    MachineUsageEntry,
    ServiceQueue,
)
from tests.data_export.portable_helpers import (
    archive_files,
    csv_rows,
    make_job,
    make_space,
    make_user,
)
from tests.encryption.conftest import enabled_encryption

pytestmark = pytest.mark.django_db(transaction=True)

DATASET_PATHS = {
    "hardware_requests.HardwareRequest": "lending/requests.csv",
    "events.EventRegistration": "events/registrations.csv",
    "bookings.Booking": "bookings/bookings.csv",
    "machines.MachineServiceRequest": "machine_service/requests.csv",
    "machines.MachineUsageEntry": "machines/usage_entries.csv",
}


def create_mapped_rows(makerspace, actor):
    now = timezone.now()
    request = HardwareRequest.objects.create(
        makerspace=makerspace,
        requester=actor,
        requester_username="pii-requester",
        requester_name="PII Hardware Name",
        requester_contact_email="pii-hardware@example.test",
        requester_contact_phone="PII-HARDWARE-PHONE",
        requested_for="Portable export test",
    )
    event = Event.objects.create(
        makerspace=makerspace,
        title="PII event fixture",
        starts_at=now + timedelta(days=1),
        ends_at=now + timedelta(days=1, hours=1),
    )
    registration = EventRegistration.objects.create(
        event=event,
        name="PII Event Name",
        email="pii-event@example.test",
        phone="PII-EVENT-PHONE",
    )
    bookable = BookableSpace.objects.create(makerspace=makerspace, name="PII room")
    booking = Booking.objects.create(
        space=bookable,
        name="PII Booking Name",
        email="pii-booking@example.test",
        phone="PII-BOOKING-PHONE",
        note="PII Booking Note",
        starts_at=now + timedelta(days=2),
        ends_at=now + timedelta(days=2, hours=1),
    )
    machine_type = MachineType.objects.create(
        makerspace=makerspace, slug="pii-machine-type", name="PII machine type"
    )
    machine = Machine.objects.create(
        makerspace=makerspace, machine_type=machine_type, name="PII machine"
    )
    queue = ServiceQueue.objects.create(
        makerspace=makerspace, machine_type=machine_type, name="PII queue"
    )
    service_request = MachineServiceRequest.objects.create(
        queue=queue,
        makerspace=makerspace,
        requester=actor,
        requester_name="PII Service Name",
        contact_email="pii-service@example.test",
        contact_phone="PII-SERVICE-PHONE",
        title="PII service request",
    )
    usage = MachineUsageEntry.objects.create(
        machine=machine,
        note="PII Usage Note",
        requester_name="PII Usage Name",
        contact_email="pii-usage@example.test",
        contact_phone="PII-USAGE-PHONE",
        title="PII usage",
    )
    return {
        row._meta.label: row
        for row in (request, registration, booking, service_request, usage)
    }


def test_portable_archive_keeps_every_mapped_value_encrypted_and_records_aad():
    actor = make_user("portable-pii-actor")
    makerspace = make_space("portable-pii")
    with enabled_encryption():
        rows = create_mapped_rows(makerspace, actor)
        plaintext = {
            value
            for row in rows.values()
            for field in mapped_field_names(row._meta.label)
            if (value := getattr(row, field))
        }
        files, archive_bytes, _manifest = archive_files(make_job(makerspace, actor))

        for label, row in rows.items():
            exported = csv_rows(files, DATASET_PATHS[label])
            assert len(exported) == 1
            for field_name in mapped_field_names(label):
                assert exported[0][field_name] not in plaintext
                assert is_envelope(exported[0][field_name])

        flattened = b"\n".join(files.values())
        for value in plaintext:
            assert value.encode() not in flattened
            assert value.encode() not in archive_bytes

        sidecar = json.loads(files["pii/aad_inputs.json"])
        entries = {entry["label"]: entry for entry in sidecar["models"]}
        for label, row in rows.items():
            entry = entries[label]
            assert entry == {
                "label": label,
                "table": row._meta.db_table,
                "fields": sorted(mapped_field_names(label)),
                "rows": {str(row.pk): makerspace.pk},
            }
            for field_name in entry["fields"]:
                assert aad_inputs(type(row).objects.get(pk=row.pk), field_name) == {
                    "makerspace_id": makerspace.pk,
                    "table": row._meta.db_table,
                    "pk": row.pk,
                    "field": field_name,
                }


def test_portable_export_rejects_plaintext_source_columns():
    actor = make_user("portable-plaintext-actor")
    makerspace = make_space("portable-plaintext")
    HardwareRequest.objects.create(
        makerspace=makerspace,
        requester=actor,
        requester_username="plaintext-user",
        requester_name="PLAINTEXT PORTABLE MUST FAIL",
        requested_for="Integrity test",
    )

    with pytest.raises(ExportIntegrityError, match="not an encrypted PII envelope"):
        archive_files(make_job(makerspace, actor))
