import json
from datetime import timedelta
from decimal import Decimal

from django.utils import timezone

from apps.accounts.models import User
from apps.backup.tenant_projection import project_dataset
from apps.events.models import Event, EventCollaborator, EventRegistration
from apps.makerspaces.models import Makerspace
from apps.operations.models import StockTransfer
from apps.payments.models import Payment


def spaces():
    own = Makerspace(pk=1, name="Own space", slug="own-space")
    foreign = Makerspace(pk=2, name="Foreign space", slug="foreign-space")
    return own, foreign


def test_event_collaboration_is_snapshot_only_in_both_directions():
    own, foreign = spaces()
    now = timezone.now()
    hosted = Event(
        pk=10, makerspace=own, title="Hosted", starts_at=now,
        ends_at=now + timedelta(hours=1),
    )
    foreign_event = Event(
        pk=11, makerspace=foreign, title="Foreign", starts_at=now,
        ends_at=now + timedelta(hours=2),
    )
    rows = [
        EventCollaborator(pk=20, event=hosted, makerspace=foreign, created_at=now),
        EventCollaborator(pk=21, event=foreign_event, makerspace=own, created_at=now),
    ]

    payload, references, included = project_dataset(
        "events.EventCollaborator", rows, own.pk
    )

    assert json.loads(payload) == []
    assert included == []
    assert {item["type"] for item in references} == {
        "hosted_event_collaborator", "foreign_host_event",
    }
    assert {item.get("host", item.get("makerspace"))["slug"] for item in references} == {
        foreign.slug
    }


def test_cross_tenant_fields_are_nulled_and_preserved_as_provenance():
    own, foreign = spaces()
    actor = User(pk=30, username="operator")
    now = timezone.now()
    event = Event(
        pk=31, makerspace=own, title="Hosted", starts_at=now,
        ends_at=now + timedelta(hours=1),
    )
    registration = EventRegistration(
        pk=32, event=event, name="Maker", email="maker@example.test", phone="",
        registered_via_makerspace=foreign, payment_via_makerspace=foreign,
        created_at=now,
    )
    payment = Payment(
        pk=33, makerspace=own, via_makerspace=foreign,
        subject_type=Payment.SubjectType.EVENT_REGISTRATION, subject_id=32,
        amount=Decimal("10.00"), currency="inr", created_by=actor,
        created_at=now, updated_at=now,
    )

    registration_json, registration_refs, _ = project_dataset(
        "events.EventRegistration", [registration], own.pk
    )
    payment_json, payment_refs, _ = project_dataset(
        "payments.Payment", [payment], own.pk
    )

    registration_fields = json.loads(registration_json)[0]["fields"]
    assert registration_fields["registered_via_makerspace"] is None
    assert registration_fields["payment_via_makerspace"] is None
    assert {item["makerspace"]["slug"] for item in registration_refs} == {foreign.slug}
    assert json.loads(payment_json)[0]["fields"]["via_makerspace"] is None
    assert payment_refs[0]["makerspace"] == {
        "name": foreign.name, "slug": foreign.slug,
    }


def test_owned_cross_space_transfer_keeps_row_but_nulls_foreign_side():
    own, foreign = spaces()
    actor = User(pk=40, username="operator")
    now = timezone.now()
    transfer = StockTransfer(
        pk=41, makerspace=own, source_makerspace=own,
        destination_makerspace=foreign, created_by=actor,
        reason="Send tool", created_at=now, applied_at=now,
    )

    payload, references, included = project_dataset(
        "operations.StockTransfer", [transfer], own.pk
    )

    fields = json.loads(payload)[0]["fields"]
    assert included == [transfer.pk]
    assert fields["source_makerspace"] == own.pk
    assert fields["destination_makerspace"] is None
    assert references[0]["makerspace"]["slug"] == foreign.slug


def test_transfer_owner_source_disagreement_fails_archive_projection():
    own, foreign = spaces()
    transfer = StockTransfer(
        pk=50, makerspace=own, source_makerspace=foreign,
        destination_makerspace=own, reason="Invalid ownership",
    )

    try:
        project_dataset("operations.StockTransfer", [transfer], own.pk)
    except ValueError as exc:
        assert "owner disagrees" in str(exc)
    else:
        raise AssertionError("An inconsistent transfer must fail the archive.")
