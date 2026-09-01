from datetime import timedelta
from importlib import import_module
from uuid import uuid4

import pytest
from django.apps import apps as django_apps
from django.db import IntegrityError, connection, transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.events.models import Event, EventRegistration
from apps.makerspaces.models import Makerspace

pytestmark = pytest.mark.django_db


def make_space(slug):
    return Makerspace.objects.create(name=slug, slug=slug)


def make_event(makerspace, **overrides):
    starts_at = timezone.now()
    defaults = {
        "makerspace": makerspace,
        "title": "Open workshop",
        "starts_at": starts_at,
        "ends_at": starts_at + timedelta(hours=2),
    }
    defaults.update(overrides)
    return Event.objects.create(**defaults)


def make_registration(event, **overrides):
    defaults = {
        "event": event,
        "name": "Ada Lovelace",
        "email": "ada@example.com",
        "phone": "+91 99999 00000",
    }
    defaults.update(overrides)
    return EventRegistration.objects.create(**defaults)


def test_event_defaults_are_draft_private_and_unlimited():
    event = make_event(make_space("event-defaults"))

    assert event.status == Event.Status.DRAFT
    assert event.is_public is False
    assert event.capacity == 0
    assert event.location_kind == Event.LocationKind.OTHER
    assert event.custom_form is None
    assert event.registration_requires_approval is False
    assert event.registration_cutoff_at is None
    assert event.registration_cutoff_lead_minutes is None


def test_registration_custom_answers_default_to_null():
    event = make_event(make_space('event-answer-defaults'))

    assert make_registration(event).custom_answers is None


def test_all_event_and_registration_statuses_round_trip():
    event = make_event(make_space("event-statuses"))
    registration = make_registration(event)

    for status in Event.Status.values:
        event.status = status
        event.save(update_fields=["status"])
        event.refresh_from_db()
        assert event.status == status

    for status in EventRegistration.Status.values:
        registration.status = status
        registration.save(update_fields=["status"])
        registration.refresh_from_db()
        assert registration.status == status


def test_database_rejects_invalid_event_interval_and_negative_capacity():
    makerspace = make_space("event-constraints")
    starts_at = timezone.now()

    with pytest.raises(IntegrityError), transaction.atomic():
        make_event(
            makerspace,
            starts_at=starts_at,
            ends_at=starts_at - timedelta(seconds=1),
        )

    with pytest.raises(IntegrityError), transaction.atomic():
        make_event(makerspace, capacity=-1)


def test_registration_email_is_unique_per_event_after_normalization():
    makerspace = make_space("event-registration-uniqueness")
    first_event = make_event(makerspace, title="First")
    second_event = make_event(makerspace, title="Second")

    first = make_registration(first_event, email="  ADA@Example.COM ")
    assert first.email == "ada@example.com"

    with pytest.raises(IntegrityError), transaction.atomic():
        make_registration(first_event, email="ada@example.com")

    other = make_registration(second_event, email="ADA@example.com")
    assert other.email == "ada@example.com"


def test_makerspace_delete_cascades_and_creator_delete_sets_null():
    creator = User.objects.create_user(username="event-creator")
    makerspace = make_space("event-delete-behavior")
    event = make_event(makerspace, created_by=creator)
    registration = make_registration(event)

    creator.delete()
    event.refresh_from_db()
    assert event.created_by is None

    # H4's tenant fence intentionally has a PROTECT FK.  Normal deletion is
    # rejected; the makerspace purge path removes the fence under its scoped
    # immutable-delete GUC before deleting the tenant graph.
    from apps.encryption.models import PiiMakerspaceWriteFence

    with transaction.atomic(), connection.cursor() as cursor:
        cursor.execute("SET LOCAL app.allow_immutable_delete = 'on'")
        PiiMakerspaceWriteFence.objects.filter(makerspace=makerspace).delete()
        makerspace.delete()
    assert not Event.objects.filter(pk=event.pk).exists()
    assert not EventRegistration.objects.filter(pk=registration.pk).exists()


def test_events_module_migration_forward_is_idempotent_and_reverse_is_targeted():
    migration = import_module(
        "apps.makerspaces.migrations.0032_enable_events_module"
    )
    first = Makerspace.objects.create(
        name="Migration One",
        slug="events-migration-one",
        enabled_modules=["custom", "machines"],
    )
    second = Makerspace.objects.create(
        name="Migration Two",
        slug="events-migration-two",
        enabled_modules=["events", "another-custom"],
    )

    migration.enable_events(django_apps, None)
    migration.enable_events(django_apps, None)
    first.refresh_from_db()
    second.refresh_from_db()
    assert first.enabled_modules == ["custom", "machines", "events"]
    assert second.enabled_modules == ["events", "another-custom"]

    migration.disable_events(django_apps, None)
    first.refresh_from_db()
    second.refresh_from_db()
    assert first.enabled_modules == ["custom", "machines"]
    assert second.enabled_modules == ["another-custom"]


def test_events_is_an_installable_module():
    # Modules are opt-in, so `events` is no longer on by default. It must still be a
    # registered module that the `everything` profile installs. (The old assertion
    # pinned its position within enabled_modules, which canonicalization sorts anyway.)
    from apps.makerspaces.models import DEFAULT_ENABLED_MODULES
    from apps.makerspaces.module_profiles import EVERYTHING, profile_modules

    assert "events" not in DEFAULT_ENABLED_MODULES
    assert "events" in profile_modules(EVERYTHING)


def test_public_token_is_generated_unique_immutable_and_not_the_internal_id():
    makerspace = make_space("event-public-token")
    first = make_event(makerspace, title="First")
    second = make_event(makerspace, title="Second")
    original_token = first.public_token

    assert original_token
    assert original_token != second.public_token
    assert str(original_token) != str(first.id)
    assert Event._meta.get_field("public_token").unique is True
    assert Event._meta.get_field("public_token").editable is False

    first.public_token = uuid4()
    first.save(update_fields=["public_token"])
    first.refresh_from_db()
    assert first.public_token == original_token
