from datetime import datetime, timedelta, timezone as utc
from types import SimpleNamespace

import pytest
from django.utils import timezone

from apps.integrations.dispatch import dispatch_email
from apps.integrations.dispatch_policy import NEVER_DEFERRED
from apps.integrations.models import EmailLog
from apps.integrations.models_timing import NotificationTimingPolicy
from apps.integrations.quiet_hours import quiet_until
from apps.notifications.models import MemberNotificationPreference
from apps.operations.models_reminders import ReminderSchedule
from apps.operations.reminder_sweeper import run_reminder_sweep
from tests.return_helpers import make_space, make_member

pytestmark = pytest.mark.django_db(transaction=True)


def world(slug, *, timezone_name='Asia/Kolkata'):
    space = make_space(slug)
    space.timezone = timezone_name
    space.enabled_modules = sorted(set(space.enabled_modules) | {'notifications', 'email'})
    space.enabled_features = sorted(set(space.enabled_features) | {'notifications.quiet_hours', 'notifications.digests'})
    space.save(update_fields=['timezone', 'enabled_modules', 'enabled_features', 'updated_at'])
    NotificationTimingPolicy.objects.create(makerspace=space, channels=['email', 'telegram'])
    return space, make_member(slug + '-member', space)


def send(space, user, event='created', feature='bookings'):
    return dispatch_email(makerspace=space, recipient_id=user.pk, to_email=user.email,
                          subject='Booking update', text_body='Your own booking',
                          feature=feature, stream='bookings', event=event, audience='requester', sync=True)


def test_overnight_local_quiet_window_and_boundary():
    space, _ = world('quiet-local-wp3')
    at = datetime(2026, 10, 11, 18, 30, tzinfo=utc.utc)  # midnight in Kolkata
    assert quiet_until(space, 'email', at) == datetime(2026, 10, 12, 2, 30, tzinfo=utc.utc)
    assert quiet_until(space, 'webhook', at) is None
    assert quiet_until(space, 'email', datetime(2026, 10, 12, 2, 30, tzinfo=utc.utc)) is None


def test_quiet_end_in_dst_gap_moves_to_real_wall_time():
    space, _ = world('quiet-gap-wp3', timezone_name='America/New_York')
    policy = NotificationTimingPolicy.objects.get(makerspace=space)
    policy.quiet_end = datetime.strptime('02:30', '%H:%M').time()
    policy.save(update_fields=['quiet_end'])
    assert quiet_until(space, 'email', datetime(2026, 3, 8, 6, tzinfo=utc.utc)) == datetime(2026, 3, 8, 7, 30, tzinfo=utc.utc)


@pytest.mark.parametrize('event', sorted(NEVER_DEFERRED))
def test_critical_events_bypass_quiet_hours_and_digest(monkeypatch, event):
    space, user = world('critical-' + event.replace('_', '-'))
    monkeypatch.setattr(timezone, 'now', lambda: datetime(2026, 10, 11, 18, 30, tzinfo=utc.utc))
    sent = []
    monkeypatch.setattr('apps.integrations.dispatch._deliver', lambda log: sent.append(log.pk) or log)
    MemberNotificationPreference.objects.create(makerspace=space, user=user, feature='bookings', channel='email', daily_digest=True)
    log = send(space, user, event)
    assert sent == [log.pk] and not ReminderSchedule.objects.filter(source='notifications.deferred').exists()


def test_quiet_mail_is_durable_and_f1_releases_it_at_most_once(monkeypatch):
    space, user = world('quiet-release-wp3')
    now = datetime(2026, 10, 11, 18, 30, tzinfo=utc.utc)
    monkeypatch.setattr(timezone, 'now', lambda: now)
    sent = []
    def deliver(log):
        sent.append(log.pk)
        log.status = 'sent'
        log.save(update_fields=['status', 'updated_at'])
        return log
    monkeypatch.setattr('apps.integrations.dispatch._deliver', deliver)
    log = send(space, user)
    assert log.status == EmailLog.Status.PENDING and sent == []
    assert ReminderSchedule.objects.get(source='notifications.deferred').subject.startswith(f'email:{log.pk}:')
    run_reminder_sweep(now=now, source_keys={'notifications.deferred'})
    assert sent == []
    now += timedelta(hours=8)
    run_reminder_sweep(now=now, source_keys={'notifications.deferred'})
    run_reminder_sweep(now=now, source_keys={'notifications.deferred'})
    assert sent == [log.pk]


def test_daily_digest_groups_only_one_users_opted_in_family_and_rechecks_opt_out(monkeypatch):
    space, user = world('digest-wp3')
    other = make_member('digest-other-wp3', space)
    now = datetime(2026, 10, 11, 5, tzinfo=utc.utc)
    monkeypatch.setattr(timezone, 'now', lambda: now)
    monkeypatch.setattr('apps.integrations.dispatch_outbox._enqueue', lambda pk: None)
    monkeypatch.setattr('apps.integrations.dispatch._deliver', lambda log: SimpleNamespace(status='sent', pk=log.pk))
    MemberNotificationPreference.objects.create(makerspace=space, user=user, feature='bookings', channel='email', daily_digest=True)
    one, two = send(space, user), send(space, user)
    immediate = send(space, other)
    assert one.error.startswith('deferred:digest:') and two.error == one.error
    assert immediate.status == 'sent'
    now += timedelta(days=1)
    run_reminder_sweep(now=now, source_keys={'notifications.deferred'})
    summary = EmailLog.objects.get(makerspace=space, event='daily_digest')
    assert summary.recipient_id == user.pk and summary.to_email == user.email
    assert summary.text_body.count('Your own booking') == 2
    assert EmailLog.objects.filter(pk__in=[one.pk, two.pk], status='skipped', error='included_in_daily_digest').count() == 2
    # A later opt-out suppresses queued rows, without putting them in the summary.
    three = send(space, user)
    MemberNotificationPreference.objects.filter(makerspace=space, user=user).update(enabled=False)
    now += timedelta(days=1)
    run_reminder_sweep(now=now, source_keys={'notifications.deferred'})
    three.refresh_from_db()
    assert three.status == 'skipped' and EmailLog.objects.filter(event='daily_digest').count() == 1


def test_revocation_before_digest_release_suppresses_queued_content(monkeypatch):
    from apps.makerspaces.models import MakerspaceMembership
    space, user = world('digest-revoked-wp3')
    now = datetime(2026, 10, 11, 5, tzinfo=utc.utc)
    monkeypatch.setattr(timezone, 'now', lambda: now)
    MemberNotificationPreference.objects.create(makerspace=space, user=user, feature='bookings', channel='email', daily_digest=True)
    queued = send(space, user)
    MakerspaceMembership.objects.filter(makerspace=space, user=user).update(status='revoked')
    now += timedelta(days=1)
    run_reminder_sweep(now=now, source_keys={'notifications.deferred'})
    queued.refresh_from_db()
    assert queued.status == 'skipped' and not EmailLog.objects.filter(event='daily_digest').exists()


def test_timing_policy_requires_scoped_manager_and_never_returns_signing_secret():
    from django.urls import reverse
    from tests.return_helpers import authenticated_client
    space, manager = world('timing-api-wp3')
    path = reverse('notification-timing-policy', kwargs={'makerspace_id': space.pk})
    stranger = make_member('timing-foreign-manager-wp3', make_space('timing-foreign-wp3'))
    assert authenticated_client(stranger).patch(path, {'channels': ['email']}, format='json').status_code in (403, 404)
    secret = 'inbound-secret-at-least-32-characters'
    client = authenticated_client(manager)
    result = client.patch(path, {'quiet_start': '21:30', 'channels': ['email'], 'bounce_secret': secret}, format='json')
    assert result.status_code == 200 and result.data['bounce_configured'] is True
    assert 'bounce_secret' not in result.data and secret not in str(result.data)
    policy = NotificationTimingPolicy.objects.get(makerspace=space)
    assert policy.bounce_secret != secret and policy.get_bounce_secret() == secret
    assert client.patch(path, {'quiet_start': '21:30:45'}, format='json').status_code == 400


def test_fully_suppressed_first_digest_batch_does_not_strand_the_tail(monkeypatch):
    from apps.integrations.models_suppression import EmailSuppression
    from apps.integrations.email_preferences import address_hash
    space, user = world('digest-tail-wp3')
    now = datetime(2026, 10, 11, 5, tzinfo=utc.utc)
    monkeypatch.setattr(timezone, 'now', lambda: now)
    monkeypatch.setattr('apps.integrations.dispatch_outbox._enqueue', lambda pk: None)
    MemberNotificationPreference.objects.create(makerspace=space, user=user, feature='bookings', channel='email', daily_digest=True)
    for _ in range(200):
        dispatch_email(makerspace=space, recipient_id=user.pk, to_email='bounced@example.test',
                       feature='bookings', stream='bookings', event='created',
                       subject='Suppressed', text_body='Do not include', sync=True)
    tail = send(space, user)
    EmailSuppression.objects.create(makerspace=space, address_hash=address_hash(space.pk, 'bounced@example.test'), reason='bounce')
    now += timedelta(days=1)
    run_reminder_sweep(now=now, source_keys={'notifications.deferred'})
    assert ReminderSchedule.objects.filter(source='notifications.deferred', kind=f'digest-tail-{tail.pk}', state='pending').exists()
    run_reminder_sweep(now=now, source_keys={'notifications.deferred'})
    summary = EmailLog.objects.get(event='daily_digest')
    assert summary.text_body == 'Booking update\nYour own booking'
    tail.refresh_from_db()
    assert tail.error == 'included_in_daily_digest'


@pytest.mark.parametrize('change', ['opt_out', 'matrix', 'revocation', 'module'])
def test_queued_digest_rechecks_family_and_standing_before_smtp(monkeypatch, change):
    from apps.integrations.dispatch_delivery import _deliver
    from apps.integrations.models import NotificationPreference
    from apps.makerspaces.models import MakerspaceMembership
    space, user = world('digest-delivery-' + change.replace('_', '-'))
    now = datetime(2026, 10, 11, 5, tzinfo=utc.utc)
    monkeypatch.setattr(timezone, 'now', lambda: now)
    monkeypatch.setattr('apps.integrations.dispatch_outbox._enqueue', lambda pk: None)
    pref = MemberNotificationPreference.objects.create(makerspace=space, user=user, feature='bookings', channel='email', daily_digest=True)
    send(space, user)
    now += timedelta(days=1)
    run_reminder_sweep(now=now, source_keys={'notifications.deferred'})
    summary = EmailLog.objects.get(event='daily_digest')
    assert summary.feature == 'bookings'
    if change == 'opt_out':
        pref.enabled = False
        pref.save(update_fields=['enabled'])
    elif change == 'matrix':
        NotificationPreference.objects.update_or_create(makerspace=space, feature='bookings', channel='email', defaults={'enabled': False})
    elif change == 'revocation':
        MakerspaceMembership.objects.filter(makerspace=space, user=user).update(status='revoked')
    else:
        from tests.module_helpers import disable_module
        disable_module(space, 'bookings')
        summary.makerspace.refresh_from_db()
    _deliver(summary)
    summary.refresh_from_db()
    assert summary.status == 'skipped' and summary.attempts == 0


def test_old_quiet_claim_cannot_release_a_newer_deferral(monkeypatch):
    from apps.integrations.reminders_deferred import dispatch
    space, user = world('quiet-moved-wp3')
    now = datetime(2026, 10, 11, 18, 30, tzinfo=utc.utc)
    monkeypatch.setattr(timezone, 'now', lambda: now)
    queued = send(space, user)
    old = ReminderSchedule.objects.get(source='notifications.deferred')
    queued.error = 'deferred:email:2026-10-13T02:30:00+00:00'
    queued.save(update_fields=['error', 'updated_at'])
    sent = []
    monkeypatch.setattr('apps.integrations.dispatch._deliver', lambda log: sent.append(log.pk))
    dispatch(space, old, None, now + timedelta(hours=8), None)
    assert sent == []


def test_redacted_sync_email_delivers_real_body_without_deferral_or_storage(monkeypatch):
    space, user = world('quiet-private-body-wp3')
    monkeypatch.setattr(timezone, 'now', lambda: datetime(2026, 10, 11, 18, 30, tzinfo=utc.utc))
    MemberNotificationPreference.objects.create(makerspace=space, user=user, feature='bookings', channel='email', daily_digest=True)
    delivered = []
    class Mail:
        def __init__(self, **values):
            delivered.append(values['body'])
        def send(self):
            return 1
    monkeypatch.setattr('apps.integrations.dispatch_delivery.EmailMultiAlternatives', Mail)
    monkeypatch.setattr('apps.integrations.email.makerspace_mail_connection', lambda space: (None, 'sender@example.test'))
    body = 'Private credential that must stay out of storage'
    log = dispatch_email(makerspace=space, recipient_id=user.pk, to_email=user.email,
                         subject='Private link', text_body=body, feature='bookings',
                         stream='bookings', event='created', sync=True, persist_body=False)
    assert delivered == [body]
    log.refresh_from_db()
    assert log.status == 'sent' and log.text_body == log.html_body == ''
    assert not ReminderSchedule.objects.filter(source='notifications.deferred').exists()
