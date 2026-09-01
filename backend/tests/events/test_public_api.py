from datetime import timedelta
from uuid import uuid4

import pytest
from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.test import APIClient

from apps.audit.models import AuditLog
from apps.events.models import Event, EventRegistration
from apps.events.views_public import PublicEventListView, PublicEventRegistrationView
from apps.makerspaces.models import Makerspace
from tests.member_submission import active_member_client


pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def clear_throttles():
    cache.clear()
    yield
    cache.clear()


def make_space(slug='public-events', **values):
    return Makerspace.objects.create(name=slug, slug=slug, **values)


def make_event(space, title='Workshop', **values):
    start = values.pop('starts_at', timezone.now() + timedelta(days=1))
    end = values.pop('ends_at', start + timedelta(hours=2))
    defaults = {
        'starts_at': start,
        'ends_at': end,
        'is_public': True,
        'status': Event.Status.PUBLISHED,
    }
    defaults.update(values)
    return Event.objects.create(makerspace=space, title=title, **defaults)


def make_registration(event, email, status=EventRegistration.Status.REGISTERED):
    return EventRegistration.objects.create(
        event=event,
        name='Guest',
        email=email,
        phone='1234567890',
        status=status,
    )


def list_url(identifier):
    return reverse('public-event-list', kwargs={'makerspace_slug': identifier})


def register_url(identifier, event):
    return reverse(
        'public-event-register',
        kwargs={
            'makerspace_slug': identifier,
            'public_token': event.public_token,
        },
    )


def registration_payload(**values):
    data = {}
    data.update(values)
    return data


def test_public_read_views_are_allow_any_and_registration_requires_authentication():
    assert PublicEventListView.permission_classes == [AllowAny]
    assert PublicEventRegistrationView.permission_classes == [IsAuthenticated]
    space = make_space()
    space.enabled_modules = [key for key in space.enabled_modules if key != 'events']
    space.save(update_fields=['enabled_modules'])

    response = APIClient().get(list_url(space.slug))

    assert response.status_code == 400
    assert response.data == {'module': 'events is disabled for this makerspace.'}
    assert APIClient().get(list_url('unknown-space')).status_code == 404


def test_list_filters_by_tenant_slug_or_code_and_orders_without_n_plus_one(
    django_assert_num_queries,
):
    space = make_space()
    other = make_space('other-public-events')
    same_start = timezone.now() + timedelta(days=2)
    first = make_event(space, 'First', starts_at=same_start)
    second = make_event(space, 'Second', starts_at=same_start)
    earlier = make_event(
        space,
        'Earlier',
        starts_at=same_start - timedelta(hours=1),
        ends_at=same_start + timedelta(hours=1),
    )
    make_event(space, 'Private', is_public=False)
    make_event(space, 'Draft', status=Event.Status.DRAFT)
    make_event(
        space,
        'Ended',
        starts_at=timezone.now() - timedelta(hours=2),
        ends_at=timezone.now() - timedelta(seconds=1),
    )
    make_event(space, 'Cancelled', status=Event.Status.CANCELLED)
    make_event(other, 'Other tenant')

    # Four, not two, and each addition is a CONSTANT one, not an N+1:
    #   +1 since Phase 5A -- the deployment recovery gate is first in MIDDLEWARE and resolves
    #      its mode from the database before any request is served, deliberately uncached
    #      because a TTL would leave a just-quarantined deployment serving traffic;
    #   +1 for the organizers prefetch, since a public event now names the organizations that
    #      organize it alongside its host venue.
    # The property this test actually protects is that the count does not grow with the number
    # of events -- asserted below rather than only claimed here.
    with django_assert_num_queries(4):
        response = APIClient().get(list_url(space.slug))

    assert response.status_code == 200
    assert [row['public_token'] for row in response.data] == [
        str(earlier.public_token),
        str(first.public_token),
        str(second.public_token),
    ]
    by_code = APIClient().get(list_url(space.public_code))
    assert by_code.status_code == 200
    assert by_code.data == response.data

    # Same budget with more events in the response: that is what "no N+1" means, and a magic
    # number nobody re-derives is how an N+1 gets absorbed into it later.
    make_event(space, 'Fourth', starts_at=same_start + timedelta(hours=2))
    make_event(space, 'Fifth', starts_at=same_start + timedelta(hours=3))
    with django_assert_num_queries(4):
        grown = APIClient().get(list_url(space.slug))
    assert grown.status_code == 200
    assert len(grown.data) == 5


def test_availability_uses_only_confirmed_statuses_and_handles_capacity_edges():
    space = make_space()
    limited = make_event(space, 'Limited', capacity=3)
    overfull = make_event(space, 'Overfull', capacity=1)
    unlimited = make_event(space, 'Unlimited', capacity=0)
    for status, email in (
        (EventRegistration.Status.REGISTERED, 'registered@example.com'),
        (EventRegistration.Status.ATTENDED, 'attended@example.com'),
        (EventRegistration.Status.WAITLISTED, 'waitlisted@example.com'),
        (EventRegistration.Status.CANCELLED, 'cancelled@example.com'),
    ):
        make_registration(limited, email, status)
    make_registration(overfull, 'one@example.com')
    make_registration(overfull, 'two@example.com')

    rows = {
        row['title']: row for row in APIClient().get(list_url(space.slug)).data
    }

    assert rows['Limited']['availability'] == 'Limited'
    assert rows['Overfull']['availability'] == 'Full'
    assert rows['Unlimited']['availability'] == 'Available'
    for row in rows.values():
        assert row['availability'] in {'Available', 'Limited', 'Full'}
        assert 'spots_left' not in row


def test_availability_is_coarse_across_registration_and_bucket_boundaries():
    space = make_space()
    event = make_event(space, capacity=10)
    _, client = active_member_client(space, 'coarse-registration-member')

    before = client.get(list_url(space.slug)).data[0]
    registered = client.post(
        register_url(space.slug, event),
        registration_payload(),
        format='json',
    )
    after = client.get(list_url(space.slug)).data[0]

    assert registered.status_code == 201
    assert before['availability'] == after['availability'] == 'Available'
    assert 'spots_left' not in before
    assert 'spots_left' not in after

    for index in range(1, 8):
        make_registration(event, f'limited-{index}@example.com')
    assert client.get(list_url(space.slug)).data[0]['availability'] == 'Limited'

    make_registration(event, 'full-one@example.com')
    make_registration(event, 'full-two@example.com')
    assert client.get(list_url(space.slug)).data[0]['availability'] == 'Full'

    unlimited = make_event(space, 'Unlimited', capacity=0)
    make_registration(unlimited, 'unlimited@example.com')
    rows = {row['title']: row for row in client.get(list_url(space.slug)).data}
    assert rows['Unlimited']['availability'] == 'Available'


def test_registration_by_list_token_returns_status_only_and_waitlists_when_full():
    space = make_space()
    event = make_event(space, capacity=1)
    public_token = APIClient().get(list_url(space.slug)).data[0]['public_token']
    assert public_token == str(event.public_token)
    url = reverse(
        'public-event-register',
        kwargs={'makerspace_slug': space.slug, 'public_token': public_token},
    )

    _, registered_client = active_member_client(space, 'registered-event-member')
    _, waitlisted_client = active_member_client(space, 'waitlisted-event-member')
    registered = registered_client.post(url, registration_payload(), format='json')
    waitlisted = waitlisted_client.post(
        url,
        registration_payload(),
        format='json',
    )

    assert registered.status_code == waitlisted.status_code == 201
    assert registered.data == {'status': EventRegistration.Status.REGISTERED}
    assert waitlisted.data == {'status': EventRegistration.Status.WAITLISTED}


def test_honeypot_precedes_submission_validation_and_blank_value_proceeds():
    space = make_space()
    event = make_event(space)
    url = register_url(space.slug, event)
    _, client = active_member_client(space, 'honeypot-event-member')

    decoy = client.post(url, {'website': ' bot.example '}, format='json')

    assert decoy.status_code == 201
    assert decoy.data == {'status': EventRegistration.Status.REGISTERED}
    assert not event.registrations.exists()
    assert not AuditLog.objects.filter(action='event.registration_created').exists()

    blank = client.post(
        url,
        registration_payload(website='   '),
        format='json',
    )
    assert blank.status_code == 201
    assert event.registrations.count() == 1


def test_blank_member_submission_uses_account_derived_identity():
    space = make_space()
    event = make_event(space)
    user, client = active_member_client(
        space,
        'derived-event-member',
        display_name='Account registration name',
        email='account-registration@example.test',
        phone='9988776655',
    )
    response = client.post(
        register_url(space.slug, event),
        {'website': ''},
        format='json',
    )
    assert response.status_code == 201
    registration = event.registrations.get()
    assert (registration.member, registration.name, registration.email, registration.phone) == (
        user, 'Account registration name', 'account-registration@example.test', '9988776655',
    )


def test_registration_targets_are_slug_scoped_and_public_open_only():
    space = make_space()
    other = make_space('other-registration-space')
    now = timezone.now()
    private = make_event(space, 'Private', is_public=False)
    draft = make_event(space, 'Draft', status=Event.Status.DRAFT)
    cancelled = make_event(space, 'Cancelled', status=Event.Status.CANCELLED)
    completed = make_event(space, 'Completed', status=Event.Status.COMPLETED)
    ended = make_event(
        space,
        'Ended',
        starts_at=now - timedelta(hours=2),
        ends_at=now - timedelta(seconds=1),
    )
    open_event = make_event(space, 'Open')

    _, client = active_member_client(space, 'event-target-member')
    for target in (private, draft, cancelled, completed, ended):
        assert client.post(
            register_url(space.slug, target), registration_payload(), format='json'
        ).status_code == 404
    assert client.post(
        register_url(other.slug, open_event), registration_payload(), format='json'
    ).status_code == 404
    assert client.post(
        register_url(other.public_code, open_event), registration_payload(), format='json'
    ).status_code == 404
    missing_url = reverse(
        'public-event-register',
        kwargs={'makerspace_slug': space.slug, 'public_token': uuid4()},
    )
    assert client.post(missing_url, registration_payload(), format='json').status_code == 404


def test_cancelled_email_reregisters_and_active_duplicate_matches_generic_response():
    space = make_space()
    event = make_event(space, capacity=3)
    user, client = active_member_client(
        space, 'cancelled-event-member', email='guest@example.com'
    )
    cancelled = make_registration(
        event,
        'guest@example.com',
        EventRegistration.Status.CANCELLED,
    )
    cancelled.member = user
    cancelled.save(update_fields=['member'])
    original_created_at = timezone.now() - timedelta(days=1)
    EventRegistration.objects.filter(pk=cancelled.pk).update(
        created_at=original_created_at,
    )

    reactivated = client.post(
        register_url(space.slug, event),
        registration_payload(),
        format='json',
    )
    _, fresh_client = active_member_client(space, 'fresh-event-member')
    fresh = fresh_client.post(
        register_url(space.slug, event),
        registration_payload(),
        format='json',
    )
    duplicate = client.post(
        register_url(space.slug, event),
        registration_payload(),
        format='json',
    )

    cancelled.refresh_from_db()
    assert reactivated.status_code == 201
    assert reactivated.data == {'status': EventRegistration.Status.REGISTERED}
    assert cancelled.status == EventRegistration.Status.REGISTERED
    assert cancelled.created_at > original_created_at
    assert event.registrations.filter(email='guest@example.com').count() == 1
    assert {
        'registration_id': cancelled.pk,
        'status': EventRegistration.Status.REGISTERED,
    } in AuditLog.objects.filter(
        action='event.registration_created',
    ).values_list('meta', flat=True)
    assert duplicate.status_code == fresh.status_code == 201
    assert duplicate.data == fresh.data == {
        'status': EventRegistration.Status.REGISTERED,
    }
    assert set(duplicate.data) == {'status'}
    assert 'guest@example.com' not in str(duplicate.data).lower()


def test_duplicate_on_full_event_matches_fresh_waitlisted_response():
    space = make_space()
    event = make_event(space, capacity=1)
    existing_user, existing_client = active_member_client(
        space, 'full-event-member', email='guest@example.com'
    )
    existing = make_registration(event, 'guest@example.com')
    existing.member = existing_user
    existing.save(update_fields=['member'])

    _, fresh_client = active_member_client(space, 'fresh-full-event-member')
    fresh = fresh_client.post(
        register_url(space.slug, event),
        registration_payload(),
        format='json',
    )
    duplicate = existing_client.post(
        register_url(space.slug, event),
        registration_payload(),
        format='json',
    )

    assert duplicate.status_code == fresh.status_code == 201
    assert duplicate.data == fresh.data == {
        'status': EventRegistration.Status.WAITLISTED,
    }
    assert set(duplicate.data) == {'status'}
    assert 'guest@example.com' not in str(duplicate.data).lower()


def test_member_registration_audit_is_attributed_and_pii_free():
    space = make_space()
    event = make_event(space)
    user, client = active_member_client(
        space,
        'private-audit-member',
        display_name='Private Audit Name',
        email='private-audit@example.com',
        phone='9988776655',
    )

    response = client.post(
        register_url(space.slug, event), registration_payload(), format='json'
    )

    assert response.status_code == 201
    log = AuditLog.objects.get(action='event.registration_created')
    assert log.actor == user
    assert log.makerspace == space
    audit_text = str(log.meta).lower()
    for pii in ('private-audit@example.com', 'private audit name', '9988776655'):
        assert pii not in audit_text


def test_eleventh_hourly_registration_is_throttled_but_listing_is_unaffected():
    space = make_space()
    event = make_event(space, capacity=0)
    url = register_url(space.slug, event)
    _, client = active_member_client(space, 'throttled-event-member')

    for index in range(10):
        response = client.post(
            url,
            registration_payload(),
            format='json',
        )
        assert response.status_code == 201

    assert client.post(
        url, registration_payload(), format='json'
    ).status_code == 429
    assert client.get(list_url(space.slug)).status_code == 200
