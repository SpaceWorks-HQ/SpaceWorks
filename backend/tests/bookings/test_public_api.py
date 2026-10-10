from datetime import timedelta
from uuid import uuid4

import pytest
from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.test import APIClient

from apps.apiclients.throttling import ClientTierRateThrottle
from apps.audit.models import AuditLog
from apps.bookings.models import BookableSpace, Booking
from apps.bookings.views_public import (
    PublicBookableSpaceListView,
    PublicBookingSubmissionView,
    PublicSpaceAvailabilityView,
)
from apps.makerspaces.models import Makerspace
from tests.member_submission import active_member_client


pytestmark = pytest.mark.django_db

@pytest.fixture(autouse=True)
def clear_throttles():
    cache.clear()
    yield
    cache.clear()


def make_makerspace(slug='public-bookings'):
    return Makerspace.objects.create(name=slug, slug=slug)


def make_space(makerspace, name='Room', **values):
    defaults = {'is_public': True, 'is_active': True}
    defaults.update(values)
    return BookableSpace.objects.create(
        makerspace=makerspace,
        name=name,
        **defaults,
    )


def make_booking(space, name='Booker', status=Booking.Status.CONFIRMED, **values):
    starts_at = values.pop('starts_at', timezone.now() + timedelta(days=2))
    return Booking.objects.create(
        space=space,
        name=name,
        email=values.pop('email', 'booker@example.com'),
        phone=values.pop('phone', '1234567890'),
        starts_at=starts_at,
        ends_at=values.pop('ends_at', starts_at + timedelta(hours=1)),
        status=status,
        **values,
    )


def list_url(makerspace):
    return reverse(
        'public-bookable-space-list',
        kwargs={'makerspace_slug': makerspace.slug},
    )
def availability_url(makerspace, space):
    return reverse(
        'public-space-availability',
        kwargs={
            'makerspace_slug': makerspace.slug,
            'public_token': space.public_token,
        },
    )
def booking_url(makerspace, space):
    return reverse(
        'public-booking-submit',
        kwargs={
            'makerspace_slug': makerspace.slug,
            'public_token': space.public_token,
        },
    )
def window(start=None, end=None):
    start = start or timezone.now() + timedelta(days=1)
    end = end or start + timedelta(days=7)
    return {'starts_at': start.isoformat(), 'ends_at': end.isoformat()}
def submission(**values):
    start = timezone.now() + timedelta(days=1)
    payload = {
        'starts_at': start.isoformat(),
        'ends_at': (start + timedelta(hours=1)).isoformat(),
    }
    payload.update(values)
    return payload


def test_public_view_authentication_and_throttle_scopes_are_exact():
    for view in (PublicBookableSpaceListView, PublicSpaceAvailabilityView):
        assert view.authentication_classes == []
        assert view.permission_classes == [AllowAny]
        assert view.throttle_classes == [ClientTierRateThrottle]
    assert PublicBookingSubmissionView.permission_classes == [IsAuthenticated]
    assert PublicBookingSubmissionView.throttle_classes == [ClientTierRateThrottle]
    assert PublicBookableSpaceListView.throttle_scope == 'public_read'
    assert PublicSpaceAvailabilityView.throttle_scope == 'public_read'
    assert PublicBookingSubmissionView.throttle_scope == 'booking_submit'


def test_list_is_tenant_scoped_public_active_ordered_and_exact():
    makerspace = make_makerspace()
    other = make_makerspace('other-public-bookings')
    second = make_space(makerspace, 'Zulu')
    first = make_space(makerspace, 'Alpha', capacity=4, location='North wall')
    make_space(makerspace, 'Private', is_public=False)
    make_space(makerspace, 'Inactive', is_active=False)
    make_space(other, 'Other tenant')

    response = APIClient().get(list_url(makerspace))

    assert response.status_code == 200
    assert [row['public_token'] for row in response.data] == [
        str(first.public_token),
        str(second.public_token),
    ]
    assert set(response.data[0]) == {
        'public_token', 'name', 'kind', 'description', 'capacity', 'location',
        'image_url', 'approval_mode', 'custom_form',
        'show_public_availability', 'show_public_booker_names',
    }


def test_availability_visibility_flags_and_confirmed_overlap_only():
    makerspace = make_makerspace()
    hidden = make_space(makerspace, 'Hidden')
    unnamed = make_space(
        makerspace,
        'Unnamed',
        show_public_availability=True,
    )
    named = make_space(
        makerspace,
        'Named',
        show_public_availability=True,
        show_public_booker_names=True,
    )
    for space in (hidden, unnamed, named):
        make_booking(space, f'{space.name} confirmed')
        make_booking(space, f'{space.name} pending', status=Booking.Status.PENDING)
    bounds = window()
    client = APIClient()

    hidden_response = client.get(availability_url(makerspace, hidden), bounds)
    unnamed_response = client.get(availability_url(makerspace, unnamed), bounds)
    named_response = client.get(availability_url(makerspace, named), bounds)

    assert hidden_response.data['availability'] is None
    assert unnamed_response.data['availability'] == [
        {
            'starts_at': unnamed.bookings.get(status='confirmed').starts_at.isoformat()
            .replace('+00:00', 'Z'),
            'ends_at': unnamed.bookings.get(status='confirmed').ends_at.isoformat()
            .replace('+00:00', 'Z'),
            'booker_name': None,
        }
    ]
    assert named_response.data['availability'][0]['booker_name'] == 'Named confirmed'
    assert len(named_response.data['availability']) == 1
    assert set(named_response.data) == {
        'public_token', 'starts_at', 'ends_at', 'availability', 'timezone', 'opening_intervals'
    }


@pytest.mark.parametrize(
    'params',
    [
        {},
        {'starts_at': '2026-07-17T10:00:00', 'ends_at': '2026-07-18T10:00:00'},
        window(
            timezone.now() + timedelta(days=1),
            timezone.now() + timedelta(days=33),
        ),
        window(
            timezone.now() + timedelta(days=2),
            timezone.now() + timedelta(days=1),
        ),
    ],
)
def test_availability_rejects_invalid_or_unbounded_windows(params):
    makerspace = make_makerspace()
    response = APIClient().get(
        availability_url(makerspace, make_space(makerspace)),
        params,
    )
    assert response.status_code == 400


@pytest.mark.parametrize(
    ('approval_mode', 'expected_status'),
    [
        (BookableSpace.ApprovalMode.INSTANT, Booking.Status.CONFIRMED),
        (BookableSpace.ApprovalMode.APPROVE, Booking.Status.PENDING),
    ],
)
def test_submission_uses_service_approval_mode_and_validates_custom_answers(
    approval_mode,
    expected_status,
    monkeypatch,
):
    monkeypatch.setattr(
        'apps.bookings.notifications.notify_booking_status',
        lambda booking, event: None,
    )
    makerspace = make_makerspace()
    custom_form = [{
        'id': 'purpose', 'label': 'Purpose', 'type': 'short_text',
        'options': [], 'required': True,
    }]
    space = make_space(
        makerspace,
        approval_mode=approval_mode,
        custom_form=custom_form,
    )

    _, client = active_member_client(makerspace, 'booking-form-member')
    response = client.post(
        booking_url(makerspace, space),
        submission(custom_answers={'purpose': '  Build robot  '}),
        format='json',
    )

    assert response.status_code == 201
    assert response.data == {'status': expected_status}
    booking = space.bookings.get()
    assert booking.status == expected_status
    assert booking.custom_answers['answers'][0]['value'] == 'Build robot'


@pytest.mark.parametrize(
    'approval_mode, expected_status',
    [
        (BookableSpace.ApprovalMode.INSTANT, Booking.Status.CONFIRMED),
        (BookableSpace.ApprovalMode.APPROVE, Booking.Status.PENDING),
    ],
)
def test_honeypot_is_a_silent_mode_aware_decoy(
    approval_mode,
    expected_status,
    monkeypatch,
):
    notified = []
    monkeypatch.setattr(
        'apps.bookings.notifications.notify_booking_status',
        lambda *args: notified.append(args),
    )
    makerspace = make_makerspace()
    space = make_space(makerspace, approval_mode=approval_mode)

    _, client = active_member_client(makerspace, 'booking-honeypot-member')
    response = client.post(
        booking_url(makerspace, space),
        {'website': ' bot.example '},
        format='json',
    )

    assert response.status_code == 201
    assert response.data == {'status': expected_status}
    assert not space.bookings.exists()
    assert not AuditLog.objects.filter(action='booking.created').exists()
    assert notified == []


def test_module_disabled_is_400_and_targets_are_public_active_tenant_scoped():
    makerspace = make_makerspace()
    other = make_makerspace('other-booking-targets')
    public = make_space(makerspace)
    private = make_space(makerspace, 'Private', is_public=False)
    inactive = make_space(makerspace, 'Inactive', is_active=False)
    _, client = active_member_client(makerspace, 'booking-target-member')
    for target in (private, inactive):
        assert client.get(
            availability_url(makerspace, target), window()
        ).status_code == 404
    _, other_client = active_member_client(other, 'other-booking-target-member')
    assert other_client.post(
        booking_url(other, public), submission(), format='json'
    ).status_code == 404
    missing = reverse(
        'public-booking-submit',
        kwargs={'makerspace_slug': makerspace.slug, 'public_token': uuid4()},
    )
    assert client.post(missing, submission(), format='json').status_code == 404

    makerspace.enabled_modules.remove('bookings')
    makerspace.save(update_fields=['enabled_modules'])
    assert client.get(list_url(makerspace)).status_code == 400
    assert client.get(
        availability_url(makerspace, public), window()
    ).status_code == 400
    assert client.post(
        booking_url(makerspace, public), {'website': 'bot'}, format='json'
    ).status_code == 400
