from datetime import datetime, timedelta, timezone as datetime_timezone

import pytest
from django.db import IntegrityError, transaction
from django.urls import reverse
from rest_framework import serializers
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.bookings import services, services_bookings
from apps.bookings.exceptions import BookingConflict, BookingInvalidTransition
from apps.bookings.models import BookableSpace, Booking
from apps.makerspaces.models import Makerspace, MakerspaceMembership

pytestmark = pytest.mark.django_db


def make_makerspace(slug='booking-rules', **values):
    return Makerspace.objects.create(name=slug, slug=slug, **values)


def make_space(makerspace=None, **values):
    defaults = {
        'makerspace': makerspace or make_makerspace(),
        'name': 'Development Room',
    }
    defaults.update(values)
    return BookableSpace.objects.create(**defaults)


def make_user(name, makerspace=None, role=None):
    actor = User.objects.create_user(
        username=name,
        access_status=User.AccessStatus.ACTIVE,
    )
    if makerspace is not None:
        MakerspaceMembership.objects.create(
            user=actor,
            makerspace=makerspace,
            role=role or MakerspaceMembership.Role.SPACE_MANAGER,
        )
    return actor


def client_for(actor):
    client = APIClient()
    client.force_authenticate(actor)
    return client


def create_booking(space, starts_at, ends_at):
    return services.create_booking(
        space,
        name='Ada',
        email='ada@example.com',
        phone='123',
        starts_at=starts_at,
        ends_at=ends_at,
    )


def test_space_booking_rule_defaults_and_database_constraints():
    makerspace = make_makerspace('booking-rule-defaults')
    space = make_space(makerspace)

    assert space.min_booking_duration_minutes == 30
    assert space.max_booking_duration_minutes == 480
    assert space.booking_lead_time_minutes == 60
    assert space.max_booking_advance_days == 30

    invalid_values = (
        {'name': 'Bad minimum', 'min_booking_duration_minutes': 0},
        {
            'name': 'Bad maximum',
            'min_booking_duration_minutes': 60,
            'max_booking_duration_minutes': 59,
        },
        {'name': 'Bad advance', 'max_booking_advance_days': 0},
    )
    for values in invalid_values:
        with pytest.raises(IntegrityError), transaction.atomic():
            make_space(makerspace, **values)


def test_update_booking_rules_rejects_unknown_inactive_and_combined_invalid():
    space = make_space()
    with pytest.raises(serializers.ValidationError) as unknown:
        services.update_booking_rules(space, actor=None, name='No')
    assert unknown.value.detail == {
        'name': serializers.ErrorDetail(
            'This field cannot be updated.',
            code='invalid',
        )
    }

    inactive = make_space(make_makerspace('booking-rules-inactive'), is_active=False)
    with pytest.raises(BookingInvalidTransition):
        services.update_booking_rules(
            inactive,
            actor=None,
            max_booking_duration_minutes=120,
        )

    space.min_booking_duration_minutes = 90
    space.save(update_fields=['min_booking_duration_minutes'])
    with pytest.raises(serializers.ValidationError) as invalid:
        services.update_booking_rules(
            space,
            actor=None,
            max_booking_duration_minutes=60,
        )
    assert set(invalid.value.detail) == {'max_booking_duration_minutes'}
    assert not AuditLog.objects.filter(
        action='booking.space_rules_updated'
    ).exists()


def test_update_booking_rules_saves_changed_fields_and_audits(monkeypatch):
    makerspace = make_makerspace('booking-rules-update')
    actor = make_user('booking-rules-actor')
    space = make_space(makerspace)
    saved_fields = []
    original_save = BookableSpace.save

    def capture_save(instance, *args, **kwargs):
        saved_fields.append(kwargs.get('update_fields'))
        return original_save(instance, *args, **kwargs)

    monkeypatch.setattr(BookableSpace, 'save', capture_save)
    updated = services.update_booking_rules(
        space,
        actor=actor,
        booking_lead_time_minutes=90,
        max_booking_advance_days=45,
    )

    assert updated.booking_lead_time_minutes == 90
    assert updated.max_booking_advance_days == 45
    assert updated.min_booking_duration_minutes == 30
    assert saved_fields == [[
        'booking_lead_time_minutes',
        'max_booking_advance_days',
        'updated_at',
    ]]
    log = AuditLog.objects.get(action='booking.space_rules_updated')
    assert log.makerspace == makerspace
    assert log.actor == actor
    assert log.meta == {
        'changed_fields': [
            'booking_lead_time_minutes',
            'max_booking_advance_days',
        ]
    }

    updated = services.update_booking_rules(
        updated,
        actor=actor,
        approval_mode=BookableSpace.ApprovalMode.APPROVE,
    )
    assert updated.approval_mode == BookableSpace.ApprovalMode.APPROVE


@pytest.mark.parametrize(
    ('starts_delta', 'duration', 'field'),
    (
        (timedelta(hours=2), timedelta(minutes=29), 'ends_at'),
        (timedelta(hours=2), timedelta(minutes=481), 'ends_at'),
        (timedelta(minutes=59), timedelta(minutes=60), 'starts_at'),
        (timedelta(days=30, seconds=1), timedelta(minutes=60), 'starts_at'),
    ),
)
def test_create_booking_rejects_rule_failures_without_rows_or_audit(
    monkeypatch, starts_delta, duration, field
):
    now = datetime(2030, 1, 1, tzinfo=datetime_timezone.utc)
    monkeypatch.setattr(services_bookings.timezone, 'now', lambda: now)
    space = make_space()
    before = AuditLog.objects.count()
    starts_at = now + starts_delta

    with pytest.raises(serializers.ValidationError) as caught:
        create_booking(space, starts_at, starts_at + duration)

    assert set(caught.value.detail) == {field}
    assert not Booking.objects.filter(space=space).exists()
    assert AuditLog.objects.count() == before


@pytest.mark.parametrize(
    ('starts_delta', 'duration'),
    (
        (timedelta(hours=2), timedelta(minutes=30)),
        (timedelta(hours=2), timedelta(minutes=480)),
        (timedelta(minutes=60), timedelta(minutes=60)),
        (timedelta(days=30), timedelta(minutes=60)),
    ),
)
def test_create_booking_allows_exact_rule_boundaries(
    monkeypatch, starts_delta, duration
):
    now = datetime(2030, 1, 1, tzinfo=datetime_timezone.utc)
    monkeypatch.setattr(services_bookings.timezone, 'now', lambda: now)
    space = make_space()
    starts_at = now + starts_delta

    booking = create_booking(space, starts_at, starts_at + duration)

    assert booking.pk is not None


def test_valid_booking_still_creates_and_overlap_still_conflicts(monkeypatch):
    now = datetime(2030, 1, 1, tzinfo=datetime_timezone.utc)
    monkeypatch.setattr(services_bookings.timezone, 'now', lambda: now)
    space = make_space()
    starts_at = now + timedelta(hours=2)
    first = create_booking(space, starts_at, starts_at + timedelta(hours=1))
    before = AuditLog.objects.count()

    with pytest.raises(BookingConflict):
        create_booking(
            space,
            starts_at + timedelta(minutes=30),
            starts_at + timedelta(minutes=90),
        )

    assert first.status == Booking.Status.CONFIRMED
    assert Booking.objects.filter(space=space).count() == 1
    assert AuditLog.objects.count() == before


def test_booking_rules_api_scopes_updates_and_general_patch():
    makerspace = make_makerspace('booking-rules-api')
    manager = make_user('booking-rules-manager', makerspace)
    inventory_manager = make_user(
        'booking-rules-inventory',
        makerspace,
        MakerspaceMembership.Role.INVENTORY_MANAGER,
    )
    other_manager = make_user(
        'booking-rules-other',
        make_makerspace('booking-rules-other-space'),
    )
    space = make_space(makerspace)
    rules_url = reverse(
        'admin-bookable-space-booking-rules',
        kwargs={'pk': space.pk},
    )
    client = client_for(manager)

    response = client.get(rules_url)
    assert response.status_code == 200
    assert set(response.data) == {
        'min_booking_duration_minutes',
        'max_booking_duration_minutes',
        'booking_lead_time_minutes',
        'max_booking_advance_days',
        'approval_mode',
    }
    response = client.patch(
        rules_url,
        {
            'min_booking_duration_minutes': 45,
            'max_booking_duration_minutes': 120,
            'approval_mode': BookableSpace.ApprovalMode.APPROVE,
        },
        format='json',
    )
    assert response.status_code == 200
    space.refresh_from_db()
    assert (
        space.min_booking_duration_minutes,
        space.max_booking_duration_minutes,
        space.approval_mode,
    ) == (45, 120, BookableSpace.ApprovalMode.APPROVE)
    assert client_for(inventory_manager).get(rules_url).status_code == 404
    assert client_for(other_manager).get(rules_url).status_code == 404

    detail_url = reverse('admin-bookable-space-detail', kwargs={'pk': space.pk})
    assert client.patch(
        detail_url,
        {'min_booking_duration_minutes': 10},
        format='json',
    ).status_code == 200
    space.refresh_from_db()
    assert space.min_booking_duration_minutes == 45

    makerspace.enabled_modules.remove('bookings')
    makerspace.save(update_fields=['enabled_modules'])
    assert client.get(rules_url).status_code == 400


def test_booking_rules_reject_overflowing_upper_bounds():
    from apps.bookings.services_rules import (
        MAX_ADVANCE_DAYS,
        MAX_LEAD_MINUTES,
    )

    makerspace = make_makerspace('booking-rules-overflow')
    manager = make_user('booking-rules-overflow-manager', makerspace)
    space = make_space(makerspace)
    rules_url = reverse(
        'admin-bookable-space-booking-rules',
        kwargs={'pk': space.pk},
    )
    client = client_for(manager)

    over_advance = client.patch(
        rules_url,
        {'max_booking_advance_days': MAX_ADVANCE_DAYS + 1},
        format='json',
    )
    assert over_advance.status_code == 400
    assert 'max_booking_advance_days' in over_advance.data

    over_lead = client.patch(
        rules_url,
        {'booking_lead_time_minutes': MAX_LEAD_MINUTES + 1},
        format='json',
    )
    assert over_lead.status_code == 400
    assert 'booking_lead_time_minutes' in over_lead.data

    space.refresh_from_db()
    assert space.max_booking_advance_days == 30
    assert space.booking_lead_time_minutes == 60


def test_general_space_patch_cannot_change_approval_mode():
    makerspace = make_makerspace('booking-rules-approval-guard')
    manager = make_user('booking-rules-approval-manager', makerspace)
    space = make_space(makerspace)
    assert space.approval_mode == BookableSpace.ApprovalMode.APPROVE

    detail_url = reverse('admin-bookable-space-detail', kwargs={'pk': space.pk})
    response = client_for(manager).patch(
        detail_url,
        {'approval_mode': BookableSpace.ApprovalMode.INSTANT},
        format='json',
    )
    assert response.status_code == 200
    space.refresh_from_db()
    assert space.approval_mode == BookableSpace.ApprovalMode.APPROVE
