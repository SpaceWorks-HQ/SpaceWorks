from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone
from drf_spectacular.generators import SchemaGenerator
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.bookings.models import BookableSpace, Booking
from apps.bookings.serializers_public import PUBLIC_BOOKABLE_SPACE_FIELDS
from apps.makerspaces.models import Makerspace
from tests.member_submission import active_member_client


pytestmark = pytest.mark.django_db

SPACE_FIELDS = set(PUBLIC_BOOKABLE_SPACE_FIELDS)
AVAILABILITY_FIELDS = {'public_token', 'starts_at', 'ends_at', 'availability'}
INTERVAL_FIELDS = {'starts_at', 'ends_at', 'booker_name'}
FORBIDDEN_KEYS = {
    'id',
    'pk',
    'makerspace',
    'makerspace_id',
    'created_by',
    'created_by_id',
    'created_at',
    'updated_at',
    'image_key',
    'requester_notifications_enabled',
    'quota',
    'bookings',
    'email',
    'phone',
    'note',
    'custom_answers',
}


def assert_no_private_value(value, sentinels):
    if isinstance(value, dict):
        for key, nested in value.items():
            if key.lower() == 'id':
                assert nested == 'safe_question'
            else:
                assert key.lower() not in FORBIDDEN_KEYS
            assert_no_private_value(nested, sentinels)
    elif isinstance(value, list):
        for nested in value:
            assert_no_private_value(nested, sentinels)
    elif isinstance(value, str):
        lowered = value.lower()
        for sentinel in sentinels:
            assert sentinel.lower() not in lowered


def make_booking(space, prefix, status):
    start = timezone.now() + timedelta(days=2)
    return Booking.objects.create(
        space=space,
        name=f'{prefix}-name-private',
        email=f'{prefix}-email-private@example.com',
        phone=f'{prefix[:16]}-phone-private',
        starts_at=start,
        ends_at=start + timedelta(hours=1),
        status=status,
        note=f'{prefix}-note-private',
        custom_answers={
            'version': 1,
            'answers': [{
                'id': 'safe_question',
                'label': 'Safe public question',
                'type': 'short_text',
                'value': f'{prefix}-answer-private',
            }],
        },
    )


def availability_url(makerspace, space):
    return reverse(
        'public-space-availability',
        kwargs={
            'makerspace_slug': makerspace.slug,
            'public_token': space.public_token,
        },
    )


def availability_params():
    start = timezone.now() + timedelta(days=1)
    return {
        'starts_at': start.isoformat(),
        'ends_at': (start + timedelta(days=7)).isoformat(),
    }


def test_recursive_leak_sweep_across_all_public_booking_payloads(monkeypatch):
    monkeypatch.setattr(
        'apps.bookings.notifications.notify_booking_status',
        lambda booking, event: None,
    )
    creator = User.objects.create_user(
        username='creator-private-sentinel',
        email='creator-private-sentinel@example.com',
    )
    makerspace = Makerspace.objects.create(
        name='Public Booking Leak Space',
        slug='public-booking-leak-space',
        booking_requester_notifications_enabled=True,
    )
    custom_form = [{
        'id': 'safe_question',
        'label': 'Safe public question',
        'type': 'short_text',
        'options': [],
        'required': False,
    }]
    hidden = BookableSpace.objects.create(
        makerspace=makerspace,
        created_by=creator,
        name='Safe Hidden Room',
        is_public=True,
        custom_form=custom_form,
        requester_notifications_enabled=True,
    )
    unnamed = BookableSpace.objects.create(
        makerspace=makerspace,
        created_by=creator,
        name='Safe Unnamed Room',
        is_public=True,
        show_public_availability=True,
        custom_form=custom_form,
        requester_notifications_enabled=False,
    )
    named = BookableSpace.objects.create(
        makerspace=makerspace,
        created_by=creator,
        name='Safe Named Room',
        is_public=True,
        show_public_availability=True,
        show_public_booker_names=True,
        custom_form=custom_form,
    )
    all_private = {
        'creator-private-sentinel',
        'creator-private-sentinel@example.com',
    }
    for space, prefix in (
        (hidden, 'hidden-confirmed'),
        (unnamed, 'unnamed-confirmed'),
        (named, 'named-confirmed'),
    ):
        confirmed = make_booking(space, prefix, Booking.Status.CONFIRMED)
        pending = make_booking(space, f'{prefix}-pending', Booking.Status.PENDING)
        for booking in (confirmed, pending):
            all_private.update(
                {
                    booking.name,
                    booking.email,
                    booking.phone,
                    booking.note,
                    booking.custom_answers['answers'][0]['value'],
                }
            )

    client = APIClient()
    listed = client.get(
        reverse(
            'public-bookable-space-list',
            kwargs={'makerspace_slug': makerspace.slug},
        )
    )
    hidden_payload = client.get(
        availability_url(makerspace, hidden), availability_params()
    )
    unnamed_payload = client.get(
        availability_url(makerspace, unnamed), availability_params()
    )
    named_payload = client.get(
        availability_url(makerspace, named), availability_params()
    )
    submission_start = timezone.now() + timedelta(days=10)
    submitted_sentinels = {
        'submitted-name-private',
        'submitted-email-private@example.com',
        'submitted-phone-private',
        'submitted-answer-private',
    }
    _, member_client = active_member_client(
        makerspace,
        'submitted-member',
        display_name='submitted-name-private',
        email='submitted-email-private@example.com',
        phone='submitted-phone-private',
    )
    submitted = member_client.post(
        reverse(
            'public-booking-submit',
            kwargs={
                'makerspace_slug': makerspace.slug,
                'public_token': hidden.public_token,
            },
        ),
        {
            'starts_at': submission_start.isoformat(),
            'ends_at': (submission_start + timedelta(hours=1)).isoformat(),
            'custom_answers': {'safe_question': 'submitted-answer-private'},
        },
        format='json',
    )

    assert listed.status_code == 200
    assert all(set(row) == SPACE_FIELDS for row in listed.data)
    assert hidden_payload.data['availability'] is None
    assert unnamed_payload.data['availability'][0]['booker_name'] is None
    assert named_payload.data['availability'][0]['booker_name'] == (
        'named-confirmed-name-private'
    )
    for response in (hidden_payload, unnamed_payload, named_payload):
        assert response.status_code == 200
        assert set(response.data) == AVAILABILITY_FIELDS
        if response.data['availability'] is not None:
            assert all(
                set(interval) == INTERVAL_FIELDS
                for interval in response.data['availability']
            )
    assert submitted.status_code == 201
    # A space created without an override now defaults to approval-required.
    assert submitted.data == {'status': Booking.Status.PENDING}

    assert_no_private_value(listed.data, all_private | submitted_sentinels)
    assert_no_private_value(hidden_payload.data, all_private | submitted_sentinels)
    assert_no_private_value(unnamed_payload.data, all_private | submitted_sentinels)
    assert_no_private_value(
        named_payload.data,
        (all_private - {'named-confirmed-name-private'}) | submitted_sentinels,
    )
    assert_no_private_value(submitted.data, all_private | submitted_sentinels)


def test_openapi_public_booking_contract_is_leak_safe_and_complete():
    schema = SchemaGenerator().get_schema(request=None, public=True)
    components = schema['components']['schemas']
    space_schema = components['PublicBookableSpace']
    input_schema = components['PublicBookingInput']
    response_schema = components['PublicBookingResponse']
    availability_schema = components['PublicSpaceAvailability']

    assert set(space_schema['properties']) == SPACE_FIELDS
    assert set(input_schema['properties']) == {
        'starts_at', 'ends_at', 'custom_answers'
    }
    assert set(input_schema['required']) == {'starts_at', 'ends_at'}
    assert all(
        field['writeOnly'] for field in input_schema['properties'].values()
    )
    assert set(response_schema['properties']) == {'status'}
    assert set(availability_schema['properties']) == AVAILABILITY_FIELDS
    for component_name in (
        'PublicBookableSpace',
        'PublicBookingResponse',
        'PublicSpaceAvailability',
        'PublicAvailabilityInterval',
    ):
        assert 'custom_answers' not in components[component_name]['properties']

    paths = {
        '/api/v1/public/{makerspace_slug}/spaces/': ('get', {'200', '400', '404', '429'}),
        '/api/v1/public/{makerspace_slug}/spaces/{public_token}/availability/': (
            'get', {'200', '400', '404', '429'}
        ),
        '/api/v1/public/{makerspace_slug}/spaces/{public_token}/book/': (
            'post', {'201', '400', '401', '403', '404', '409', '429'}
        ),
    }
    for path, (method, codes) in paths.items():
        operation = schema['paths'][path][method]
        if method == 'post':
            assert operation.get('security')
        else:
            assert operation.get('security', []) == []
        assert codes <= set(operation['responses'])
        token_parameters = [
            parameter
            for parameter in operation.get('parameters', [])
            if parameter['name'] == 'public_token'
        ]
        if '{public_token}' in path:
            assert token_parameters[0]['schema']['format'] == 'uuid'
    conflict = schema['paths'][
        '/api/v1/public/{makerspace_slug}/spaces/{public_token}/book/'
    ]['post']['responses']['409']['content']['application/json']['schema']
    assert conflict['$ref'].endswith('/HardwareRequestError')
