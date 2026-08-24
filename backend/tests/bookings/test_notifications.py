from datetime import timedelta
from types import SimpleNamespace

import pytest
from django.utils import timezone

from apps.bookings import notifications, services
from apps.bookings.models import BookableSpace, Booking
from apps.integrations.models import (
    NotificationChannel,
    NotificationDeliveryLog,
    NotificationDeliveryStatus,
)
from apps.integrations.notify import NotificationResult
from apps.integrations.notification_catalog import is_notification_enabled
from apps.makerspaces.models import Makerspace

pytestmark = pytest.mark.django_db


def makerspace(slug, enabled):
    return Makerspace.objects.create(
        name=f'{slug} Makerspace',
        slug=slug,
        booking_requester_notifications_enabled=enabled,
    )


def space(tenant, **values):
    defaults = {
        'makerspace': tenant,
        'name': 'Workshop',
        'is_public': True,
    }
    defaults.update(values)
    return BookableSpace.objects.create(**defaults)


def book(target, start=None, **values):
    start = start or timezone.now() + timedelta(hours=2)
    defaults = {
        'name': 'Ada',
        'email': 'ada@example.com',
        'phone': '123',
        'starts_at': start,
        'ends_at': start + timedelta(hours=1),
    }
    defaults.update(values)
    return services.create_booking(target, **defaults)


def test_notification_events_use_single_requester_email_adapter(
    monkeypatch,
    django_capture_on_commit_callbacks,
):
    tenant = makerspace('booking-notify-events', True)
    instant = space(tenant, approval_mode=BookableSpace.ApprovalMode.INSTANT)
    approval = space(
        tenant,
        name='Studio',
        approval_mode=BookableSpace.ApprovalMode.APPROVE,
    )
    dispatched = []
    monkeypatch.setattr(
        'apps.integrations.notify.dispatch_email',
        lambda **kwargs: dispatched.append(kwargs) or SimpleNamespace(status='sent'),
    )

    with django_capture_on_commit_callbacks(execute=True):
        confirmed = book(instant)
    with django_capture_on_commit_callbacks(execute=True):
        submitted = book(approval)
    with django_capture_on_commit_callbacks(execute=True):
        services.approve_booking(submitted, actor=None)
    rejected = book(
        approval,
        start=submitted.ends_at,
        email='grace@example.com',
    )
    with django_capture_on_commit_callbacks(execute=True):
        services.reject_booking(rejected, actor=None)

    assert [call['event'] for call in dispatched] == [
        'created',
        'created',
        'confirmed',
        'rejected',
    ]
    assert all(
        call['stream'] == 'bookings'
        and call['audience'] == 'requester'
        and call['makerspace'] == tenant
        for call in dispatched
    )
    instant_call = dispatched[0]
    assert instant_call['to_email'] == confirmed.email
    assert tenant.name in instant_call['text_body']
    assert instant.name in instant_call['text_body']
    assert 'Status: confirmed' in instant_call['text_body']
    assert all(
        value not in instant_call['text_body']
        for value in ('123', 'custom_answers', 'public_token')
    )


@pytest.mark.parametrize(
    ('makerspace_enabled', 'space_override', 'expected'),
    (
        (False, None, 0),
        (True, None, 1),
        (True, False, 0),
        (False, True, 1),
    ),
)
def test_effective_notification_toggle_controls_delivery(
    monkeypatch,
    django_capture_on_commit_callbacks,
    makerspace_enabled,
    space_override,
    expected,
):
    slug = f'booking-notify-{makerspace_enabled}-{space_override}'
    tenant = makerspace(slug, makerspace_enabled)
    target = space(
        tenant,
        requester_notifications_enabled=space_override,
    )
    dispatched = []
    monkeypatch.setattr(
        'apps.integrations.notify.dispatch_email',
        lambda **kwargs: dispatched.append(kwargs) or SimpleNamespace(status='sent'),
    )
    with django_capture_on_commit_callbacks(execute=True):
        book(target)
    assert len(dispatched) == expected


def test_notification_callback_reloads_toggle_after_commit(
    monkeypatch,
    django_capture_on_commit_callbacks,
):
    tenant = makerspace('booking-notify-reload', True)
    target = space(tenant)
    dispatched = []
    monkeypatch.setattr(
        'apps.integrations.notify.dispatch_email',
        lambda **kwargs: dispatched.append(kwargs) or SimpleNamespace(status='sent'),
    )
    with django_capture_on_commit_callbacks(execute=False) as callbacks:
        book(target)
    assert dispatched == []
    tenant.booking_requester_notifications_enabled = False
    tenant.save(update_fields=['booking_requester_notifications_enabled'])
    for callback in callbacks:
        callback()
    assert dispatched == []


def test_notification_setup_failure_is_non_pii_and_never_breaks_mutation(
    monkeypatch,
    django_capture_on_commit_callbacks,
    caplog,
):
    tenant = makerspace('booking-notify-failure', True)
    target = space(tenant, approval_mode=BookableSpace.ApprovalMode.INSTANT)

    def fail(**kwargs):
        raise RuntimeError('ada@example.com private delivery detail')

    monkeypatch.setattr('apps.integrations.notify.dispatch_email', fail)
    with caplog.at_level('WARNING'):
        with django_capture_on_commit_callbacks(execute=True):
            created = book(target)
    created.refresh_from_db()
    assert created.status == Booking.Status.CONFIRMED
    assert Booking.objects.filter(pk=created.pk).exists()
    assert 'lifecycle_email_dispatch_failed' in caplog.text
    assert 'ada@example.com' not in caplog.text
    assert 'private delivery detail' not in caplog.text


def test_notification_seam_suppresses_unknown_events():
    target = space(makerspace('booking-notify-invalid', False))
    row = book(target)
    result = notifications.notify_booking_status(row, 'unknown')
    assert result.scheduled is False


def test_all_booking_services_emit_the_exact_lifecycle_event_once(monkeypatch):
    tenant = makerspace('booking-all-events', True)
    approval = space(
        tenant, approval_mode=BookableSpace.ApprovalMode.APPROVE,
    )
    instant = space(
        tenant,
        name='Instant',
        approval_mode=BookableSpace.ApprovalMode.INSTANT,
    )
    calls = []
    monkeypatch.setattr(
        notifications,
        'notify_booking_status',
        lambda booking, event: calls.append((booking.pk, event)),
    )

    pending = book(approval)
    services.approve_booking(pending, actor=None)
    rejected = book(approval, start=pending.ends_at, email='reject@example.com')
    services.reject_booking(rejected, actor=None)
    cancelled = book(instant, start=rejected.ends_at, email='cancel@example.com')
    services.cancel_booking(cancelled, actor=None)

    past = timezone.now() - timedelta(hours=3)
    completed = Booking.objects.create(
        space=instant, name='Complete', email='complete@example.com', phone='1',
        starts_at=past, ends_at=past + timedelta(hours=1), status='confirmed',
    )
    no_show = Booking.objects.create(
        space=instant, name='No show', email='noshow@example.com', phone='1',
        starts_at=past, ends_at=past + timedelta(hours=1), status='confirmed',
    )
    services.complete_booking(completed, actor=None)
    services.mark_no_show(no_show, actor=None)

    assert [event for _, event in calls] == [
        'created', 'confirmed', 'created', 'rejected', 'created', 'cancelled',
        'completed', 'no_show',
    ]


def test_booker_and_staff_envelopes_share_one_fanout(monkeypatch):
    tenant = makerspace('booking-shared-envelope', True)
    row = book(space(tenant))
    captured = []
    monkeypatch.setattr(
        notifications,
        'staff_emails_for_feature',
        lambda *args, **kwargs: ['staff@example.com'],
    )

    def capture(makerspace, **kwargs):
        captured.append(kwargs['build']())
        return NotificationResult(False, {}, {})

    monkeypatch.setattr(notifications, 'notify_lifecycle', capture)
    notifications.notify_booking_status(row, 'confirmed', sync=True)
    assert len(captured) == 1
    assert [(email.to_email, email.audience) for email in captured[0].emails] == [
        (row.email, 'requester'), ('staff@example.com', 'staff'),
    ]


def test_booking_defaults_and_unconfigured_telegram_fail_safely(
    django_capture_on_commit_callbacks,
):
    tenant = makerspace('booking-default-channels', True)
    assert is_notification_enabled(tenant, 'bookings', 'email') is True
    assert is_notification_enabled(tenant, 'bookings', 'telegram') is True
    assert is_notification_enabled(tenant, 'bookings', 'slack') is False
    assert is_notification_enabled(tenant, 'bookings', 'mattermost') is False
    with django_capture_on_commit_callbacks(execute=True):
        created = book(space(tenant))
    delivery = NotificationDeliveryLog.objects.get(
        makerspace=tenant,
        feature='bookings',
        event='created',
        channel=NotificationChannel.TELEGRAM,
    )
    assert delivery.status == NotificationDeliveryStatus.FAILED
    assert Booking.objects.filter(pk=created.pk).exists()
