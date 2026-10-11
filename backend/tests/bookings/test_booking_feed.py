from datetime import timedelta

import pytest
from django.urls import reverse
from icalendar import Calendar
from rest_framework.test import APIClient

from apps.bookings.models_feed import BookingCalendarFeed
from apps.bookings.services_reschedule import reschedule_booking
from tests.bookings.test_member_booking_api import setup, book, member

pytestmark = pytest.mark.django_db


def settings_url(space):
    return reverse('member-booking-feed-settings', kwargs={'makerspace_slug': space.slug})


def events(response):
    assert response.status_code == 200
    return Calendar.from_ical(response.content).walk('VEVENT')


def test_ics_contains_only_owner_bookings_and_rotation_and_revocation_invalidate_tokens():
    space, room, user, client = setup('feed-own-wp3')
    mine = book(room, user)
    other, _ = member(space, 'feed-other-wp3')
    book(room, other, starts_at=mine.starts_at + timedelta(hours=3))
    result = client.post(settings_url(space), {}, format='json')
    assert result.status_code == 200
    url = result.data['feed_url']
    token = url.rsplit('/', 1)[1].removesuffix('.ics')
    row = BookingCalendarFeed.objects.get()
    assert bytes(row.token_digest) != token.encode() and len(row.token_digest) == 32
    public = APIClient()
    response = public.get(url)
    own = events(response)
    assert len(own) == 1 and str(own[0]['UID']) == f'booking-{mine.public_token}@spaceworks'
    for private in (user.email, other.email):
        assert private.encode() not in response.content
    assert response['Cache-Control'] == 'private, no-store'
    moved = reschedule_booking(mine, actor=user, starts_at=mine.starts_at + timedelta(days=1), ends_at=mine.ends_at + timedelta(days=1))
    changed = events(public.get(url))[0]
    # RFC 5545 DATE-TIME has second precision; database timestamps retain microseconds.
    assert int(changed['SEQUENCE']) == 1 and changed['DTSTART'].dt == moved.starts_at.replace(microsecond=0)
    result = client.post(settings_url(space), {}, format='json')
    assert result.status_code == 200
    assert len(events(APIClient().get(result.data['feed_url']))) == 1
    assert public.get(url).status_code == 404
    next_url = client.post(settings_url(space), {}, format='json').data['feed_url']
    assert client.delete(settings_url(space)).status_code == 204
    assert public.get(next_url).status_code == 404


def test_wrong_tenant_module_off_and_revoked_owner_are_refused():
    from tests.module_helpers import disable_module
    from apps.makerspaces.models import MakerspaceMembership
    space, room, user, client = setup('feed-guards-wp3')
    book(room, user)
    url = client.post(settings_url(space), {}, format='json').data['feed_url']
    foreign, _, _, _ = setup('feed-foreign-wp3')
    public = APIClient()
    assert public.get(url.replace(space.slug, foreign.slug)).status_code == 404
    MakerspaceMembership.objects.filter(makerspace=space, user=user).update(status='revoked')
    assert public.get(url).status_code in (403, 404)
    for method in ('get', 'post', 'delete'):
        assert getattr(client, method)(settings_url(space)).status_code == 403
    MakerspaceMembership.objects.filter(makerspace=space, user=user).update(status='active')
    disable_module(space, 'bookings')
    assert public.get(url).status_code == 400


def test_account_only_feed_needs_no_events_or_membership_module():
    from tests.return_helpers import make_user, authenticated_client
    from tests.module_helpers import disable_module
    space, room, _, _ = setup('feed-account-wp3')
    account = make_user('feed-account-only-wp3', phone='123')
    book(room, account)
    disable_module(space, 'events')
    # WP2 removes the registry dependency. Keep the booking module installed
    # explicitly so this pins the final bookings-only configuration after merge.
    space.enabled_modules = [key for key in space.enabled_modules if key != 'membership']
    space.save(update_fields=['enabled_modules', 'updated_at'])
    client = authenticated_client(account)
    assert client.post(settings_url(space), {}, format='json').status_code == 200


def test_booking_token_is_redacted_from_wsgi_and_proxy_access_logs():
    import logging
    from pathlib import Path
    from django.test import RequestFactory
    from django.http import HttpResponse
    from apps.events.middleware import CalendarFeedLogRedactionMiddleware
    path = '/api/v1/public/space/bookings/calendar/private-booking-token.ics'
    request = RequestFactory().get(path, RAW_URI=path + '?refresh=1')
    def view(current):
        assert current.path == path  # Resolution still receives the real capability.
        assert 'private-booking-token' not in current.META['RAW_URI']
        return HttpResponse()
    CalendarFeedLogRedactionMiddleware(view)(request)
    assert request.path == request.path_info == request.META['PATH_INFO'] == path.replace('private-booking-token', '[redacted]')
    proxy = Path(__file__).resolve().parents[3] / 'frontend' / 'nginx.conf'
    assert '(event-calendar|bookings/calendar)' in proxy.read_text(encoding='utf-8')
    from config.log_setup import RequestIdFilter, JsonFormatter
    # Django's 404 log is emitted before the middleware's finally block.
    request = RequestFactory().get(path)
    record = logging.LogRecord('django.request', logging.WARNING, '', 0, 'Not Found: %s', (path,), None)
    record.request = request
    RequestIdFilter().filter(record)
    assert 'private-booking-token' not in JsonFormatter().format(record)
    assert '[redacted]' in record.getMessage() and request.path == path


def test_cancellation_updates_ics_sequence_and_status():
    from apps.bookings.services_transitions import cancel_booking
    space, room, user, client = setup('feed-cancel-wp3')
    mine = book(room, user)
    result = client.post(settings_url(space), {}, format='json')
    assert result['Cache-Control'] == 'private, no-store'
    cancel_booking(mine, actor=user, member_cancel=True)
    item = events(APIClient().get(result.data['feed_url']))[0]
    assert str(item['STATUS']) == 'CANCELLED' and int(item['SEQUENCE']) == 1


def test_hidden_tenant_cannot_be_given_a_feed_by_global_superadmin_authority():
    from tests.return_helpers import make_user, authenticated_client
    space, _, _, _ = setup('feed-hidden-wp3')
    space.superadmin_access_enabled = False
    space.save(update_fields=['superadmin_access_enabled', 'updated_at'])
    admin = make_user('feed-global-superadmin-wp3', is_superuser=True)
    assert authenticated_client(admin).post(settings_url(space)).status_code == 403
    assert not BookingCalendarFeed.objects.filter(makerspace=space, user=admin).exists()
