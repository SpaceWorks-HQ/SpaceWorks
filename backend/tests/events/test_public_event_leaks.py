from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone
from drf_spectacular.generators import SchemaGenerator
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.events.models import Event, EventRegistration
from apps.events.serializers_public import PUBLIC_EVENT_FIELDS, PublicEventSerializer
from apps.makerspaces.models import Makerspace
from tests.member_submission import active_member_client


pytestmark = pytest.mark.django_db

EXPECTED_FIELDS = {
    'public_token',
    'title',
    'description',
    'starts_at',
    'ends_at',
    'location',
    'location_kind',
    'custom_form',
    'capacity',
    'availability',
    'registration_requires_approval',
    'effective_registration_cutoff_at',
    'registration_open',
    'image_url',
    'status',
    'organizers',
    # Recurrence grouping only: {public_token, title}. The series public_token is an
    # opaque public identifier -- deliberately NOT the sequential internal series id --
    # and no public route consumes it, so it grants nothing. The title is already public
    # via the occurrence itself.
    'series',
}
FORBIDDEN_KEYS = {
    'id',
    # The resolved URL is public; the underlying object key is not part of the
    # contract and must never appear in the payload.
    'image_key',
    'pk',
    'makerspace',
    'makerspace_id',
    'created_by',
    'created_by_id',
    'created_at',
    'updated_at',
    'is_public',
    'registrations',
    'registration_counts',
    'confirmed_count',
    'occupancy',
    'remaining',
    'spots_left',
    'email',
    'phone',
    'name',
    'organizer',
    'waitlisted',
    'custom_answers',
}


def assert_no_public_leak(value, sentinels):
    if isinstance(value, dict):
        is_schema_question = set(value) == {
            'id', 'label', 'type', 'options', 'required',
        }
        for key, nested in value.items():
            if not is_schema_question:
                assert key.lower() not in FORBIDDEN_KEYS
            assert_no_public_leak(nested, sentinels)
    elif isinstance(value, list):
        for nested in value:
            assert_no_public_leak(nested, sentinels)
    elif isinstance(value, str):
        lowered = value.lower()
        for sentinel in sentinels:
            assert sentinel.lower() not in lowered


def test_public_event_exact_allowlist_and_recursive_sentinel_leak_sweep():
    sentinels = {
        'sentinel-creator',
        'creator-sentinel@example.com',
        'Sentinel Registration Name',
        'registration-sentinel@example.com',
        '+919999999999',
        'Sentinel private answer',
    }
    creator = User.objects.create_user(
        username='sentinel-creator',
        email='creator-sentinel@example.com',
    )
    space = Makerspace.objects.create(name='Leak Space', slug='event-leak-space')
    start = timezone.now() + timedelta(days=1)
    event = Event.objects.create(
        makerspace=space,
        created_by=creator,
        title='Safe public workshop',
        description='<script>alert(1)</script>',
        starts_at=start,
        ends_at=start + timedelta(hours=2),
        location='Main hall',
        location_kind=Event.LocationKind.INDOOR,
        custom_form=[{
            'id': 'private_note',
            'label': 'Private note',
            'type': 'short_text',
            'options': [],
            'required': False,
        }],
        capacity=10,
        is_public=True,
        status=Event.Status.PUBLISHED,
    )
    EventRegistration.objects.create(
        event=event,
        name='Sentinel Registration Name',
        email='registration-sentinel@example.com',
        phone='+919999999999',
        custom_answers={
            'version': 1,
            'answers': [{
                'id': 'private_note',
                'label': 'Private note',
                'type': 'short_text',
                'value': 'Sentinel private answer',
            }],
        },
        status=EventRegistration.Status.WAITLISTED,
    )

    response = APIClient().get(
        reverse(
            'public-event-list',
            kwargs={'makerspace_slug': space.slug},
        )
    )

    assert response.status_code == 200
    assert len(response.data) == 1
    row = response.data[0]
    assert set(PUBLIC_EVENT_FIELDS) == EXPECTED_FIELDS
    assert set(PublicEventSerializer().fields) == EXPECTED_FIELDS
    assert set(row) == EXPECTED_FIELDS
    assert row['public_token'] == str(event.public_token)
    assert row['description'] == '<script>alert(1)</script>'
    assert row['location_kind'] == Event.LocationKind.INDOOR
    assert row['custom_form'] == event.custom_form
    assert row['availability'] in {'Available', 'Limited', 'Full'}
    assert_no_public_leak(response.data, sentinels)
    assert_no_public_leak(PublicEventSerializer(event).data, sentinels)

    _, member_client = active_member_client(
        space,
        'another-event-member',
        display_name='Another guest',
        email='another@example.com',
    )
    registration_response = member_client.post(
        reverse(
            'public-event-register',
            kwargs={
                'makerspace_slug': space.slug,
                'public_token': event.public_token,
            },
        ),
        {
            'custom_answers': {'private_note': 'Sentinel private answer'},
        },
        format='json',
    )
    assert registration_response.status_code == 201
    assert set(registration_response.data) == {'status'}
    assert_no_public_leak(registration_response.data, sentinels)


def test_openapi_has_exact_public_contracts_and_documented_errors():
    schema = SchemaGenerator().get_schema(request=None, public=True)
    components = schema['components']['schemas']
    event_schema = components['PublicEvent']
    input_schema = components['PublicEventRegistrationInput']
    response_schema = components['PublicEventRegistrationResponse']

    assert set(event_schema['properties']) == set(PUBLIC_EVENT_FIELDS)
    availability_ref = event_schema['properties']['availability']['allOf'][0][
        '$ref'
    ]
    availability_schema = components[availability_ref.rsplit('/', 1)[-1]]
    assert availability_schema['enum'] == [
        'Available',
        'Limited',
        'Full',
    ]
    assert {'id', 'pk', 'makerspace', 'created_by'} & set(
        event_schema['properties']
    ) == set()
    assert set(input_schema['properties']) == {'custom_answers'}
    assert input_schema.get('required', []) == []
    assert all(
        field['writeOnly'] for field in input_schema['properties'].values()
    )
    assert set(response_schema['properties']) == {'status'}
    status_property = response_schema['properties']['status']
    status_ref = status_property.get('$ref') or status_property['allOf'][0]['$ref']
    assert 'pending_approval' in components[status_ref.rsplit('/', 1)[-1]]['enum']

    list_operation = schema['paths'][
        '/api/v1/public/{makerspace_slug}/events/'
    ]['get']
    register_operation = schema['paths'][
        '/api/v1/public/{makerspace_slug}/events/{public_token}/register/'
    ]['post']
    assert list_operation.get('security', []) == []
    assert register_operation.get('security')
    assert {'201', '400', '401', '403', '404', '409', '429'} <= set(
        register_operation['responses']
    )
    assert register_operation['responses']['201']['content'][
        'application/json'
    ]['schema']['$ref'].endswith('/PublicEventRegistrationResponse')
    assert register_operation['responses']['409']['content'][
        'application/json'
    ]['schema']['$ref'].endswith('/HardwareRequestError')
    for code in ('400', '404', '429'):
        error_schema = register_operation['responses'][code]['content'][
            'application/json'
        ]['schema']
        assert error_schema == {'type': 'object', 'additionalProperties': {}}
    assert '409' not in list_operation['responses']
