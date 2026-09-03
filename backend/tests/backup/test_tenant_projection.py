import json
from datetime import timedelta
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.backup.raw_projection import raw_records
from apps.backup.tenant_projection import project_raw_dataset
from apps.events.models import Event, EventCollaborator, EventRegistration
from apps.makerspaces.models import Makerspace
from apps.operations.models import StockTransfer, StockTransferLine
from apps.payments.models import Payment


pytestmark = pytest.mark.django_db


def spaces():
    own = Makerspace.objects.create(name="Own space", slug="own-space")
    foreign = Makerspace.objects.create(name="Foreign space", slug="foreign-space")
    return own, foreign


def project(label, queryset, makerspace_id):
    model = queryset.model
    records = raw_records(queryset.order_by(model._meta.pk.name), model)
    return project_raw_dataset(label, model, records, makerspace_id)


def test_event_collaboration_is_snapshot_only_in_both_directions():
    own, foreign = spaces()
    now = timezone.now()
    hosted = Event.objects.create(
        makerspace=own, title="Hosted", starts_at=now, ends_at=now + timedelta(hours=1)
    )
    foreign_event = Event.objects.create(
        makerspace=foreign,
        title="Foreign",
        starts_at=now,
        ends_at=now + timedelta(hours=2),
    )
    EventCollaborator.objects.create(event=hosted, makerspace=foreign)
    EventCollaborator.objects.create(event=foreign_event, makerspace=own)

    payload, references, included = project(
        "events.EventCollaborator",
        EventCollaborator.objects.all(),
        own.pk,
    )

    assert json.loads(payload) == []
    assert included == []
    assert {item["type"] for item in references} == {
        "hosted_event_collaborator",
        "foreign_host_event",
    }
    assert {item.get("host", item.get("makerspace"))["slug"] for item in references} == {
        foreign.slug
    }


def test_event_registration_policy_is_preserved_in_backup_projection():
    own, _foreign = spaces()
    start = timezone.now() + timedelta(days=1)
    event = Event.objects.create(
        makerspace=own,
        title="Policy event",
        starts_at=start,
        ends_at=start + timedelta(hours=1),
        registration_requires_approval=True,
        registration_cutoff_lead_minutes=60,
    )

    payload, _references, included = project(
        "events.Event", Event.objects.filter(pk=event.pk), own.pk,
    )
    fields = json.loads(payload)[0]["fields"]

    assert included == [event.pk]
    assert fields["registration_requires_approval"] is True
    assert fields["registration_cutoff_at"] is None
    assert fields["registration_cutoff_lead_minutes"] == 60


def test_cross_tenant_fields_are_nulled_and_preserved_as_provenance():
    own, foreign = spaces()
    actor = get_user_model().objects.create_user(username="operator")
    now = timezone.now()
    event = Event.objects.create(
        makerspace=own,
        title="Hosted",
        starts_at=now,
        ends_at=now + timedelta(hours=1),
    )
    registration = EventRegistration.objects.create(
        event=event,
        name="Maker",
        email="maker@example.test",
        phone="",
        registered_via_makerspace=foreign,
        payment_via_makerspace=foreign,
    )
    payment = Payment.objects.create(
        makerspace=own,
        via_makerspace=foreign,
        subject_type=Payment.SubjectType.EVENT_REGISTRATION,
        subject_id=registration.pk,
        amount=Decimal("10.00"),
        currency="inr",
        created_by=actor,
    )

    registration_json, registration_refs, _ = project(
        "events.EventRegistration",
        EventRegistration.objects.filter(pk=registration.pk),
        own.pk,
    )
    payment_json, payment_refs, _ = project(
        "payments.Payment", Payment.objects.filter(pk=payment.pk), own.pk
    )

    registration_fields = json.loads(registration_json)[0]["fields"]
    assert registration_fields["registered_via_makerspace"] is None
    assert registration_fields["payment_via_makerspace"] is None
    assert {item["makerspace"]["slug"] for item in registration_refs} == {foreign.slug}
    assert json.loads(payment_json)[0]["fields"]["via_makerspace"] is None
    assert payment_refs[0]["makerspace"] == {
        "name": foreign.name,
        "slug": foreign.slug,
    }


def test_owned_cross_space_transfer_keeps_row_but_nulls_foreign_side():
    own, foreign = spaces()
    actor = get_user_model().objects.create_user(username="transfer-operator")
    transfer = StockTransfer.objects.create(
        makerspace=own,
        source_makerspace=own,
        destination_makerspace=foreign,
        created_by=actor,
        reason="Send tool",
    )

    payload, references, included = project(
        "operations.StockTransfer",
        StockTransfer.objects.filter(pk=transfer.pk),
        own.pk,
    )

    fields = json.loads(payload)[0]["fields"]
    assert included == [transfer.pk]
    assert fields["source_makerspace"] == own.pk
    assert fields["destination_makerspace"] is None
    assert references[0]["makerspace"]["slug"] == foreign.slug


def test_inbound_transfer_is_snapshot_only_and_its_lines_are_excluded():
    own, foreign = spaces()
    transfer = StockTransfer.objects.create(
        makerspace=foreign,
        source_makerspace=foreign,
        destination_makerspace=own,
        reason="Receive tool",
    )
    line = StockTransferLine.objects.create(transfer=transfer, notes="Inbound line")

    payload, references, included = project(
        "operations.StockTransfer",
        StockTransfer.objects.filter(pk=transfer.pk),
        own.pk,
    )
    line_payload, _, included_lines = project(
        "operations.StockTransferLine",
        StockTransferLine.objects.filter(pk=line.pk),
        own.pk,
    )

    assert json.loads(payload) == []
    assert included == []
    assert references == [{
        "type": "inbound_stock_transfer",
        "source": {"name": foreign.name, "slug": foreign.slug},
        "destination": {"name": own.name, "slug": own.slug},
        "status": transfer.status,
        "recorded_at": transfer.created_at,
    }]
    assert json.loads(line_payload) == []
    assert included_lines == []


def test_transfer_owner_source_disagreement_fails_archive_projection():
    own, foreign = spaces()
    transfer = StockTransfer.objects.create(
        makerspace=own,
        source_makerspace=foreign,
        destination_makerspace=own,
        reason="Invalid ownership",
    )

    with pytest.raises(ValueError, match="owner disagrees"):
        project(
            "operations.StockTransfer",
            StockTransfer.objects.filter(pk=transfer.pk),
            own.pk,
        )
