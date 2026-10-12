"""F1 owns delayed email/chat claims; uncertain deliveries are never auto-reclaimed."""

from django.db import transaction

from apps.accounts import rbac
from apps.integrations.models import EmailLog, NotificationDeliveryLog
from apps.integrations.notify import NotificationResult
from apps.integrations.timing_dispatch import RELEASING
from apps.operations.reminder_types import ReminderMessage, ReminderSource


def _logs(space, model):
    return rbac.scope_notification_policy(model.objects.all(), makerspace_id=space.pk)


def discover(space, now, limit, tz):
    # Dispatch schedules the exact durable identity, with no subject content in F1.
    return ()


def build(space, row, now, tz):
    return ReminderMessage(title='Deferred delivery', event=row.kind)


def _allowed(log, space):
    from apps.integrations.email_preferences import blocked_reason
    from apps.integrations.dispatch_policy import email_module_blocks
    from apps.integrations.notification_catalog import is_notification_enabled, receipt_email_default
    from apps.integrations.recipients import feature_available
    from apps.notifications.preferences import STREAM_FEATURES
    family = log.feature or STREAM_FEATURES.get(getattr(log, 'stream', ''), getattr(log, 'stream', ''))
    if family and not feature_available(space, family):
        return False
    if isinstance(log, EmailLog):
        from apps.notifications.inbox import eligible_owner
        if log.recipient_id and not eligible_owner(space, log.recipient_id):
            return False
        return not (blocked_reason(space, log.to_email, user_id=log.recipient_id,
                                  feature=log.feature, stream=log.stream, event=log.event)
                    or email_module_blocks(space, log.stream, log.event)) and (
            not family or is_notification_enabled(space, family, 'email') or
            (family == 'payments' and log.event == 'payment_received' and receipt_email_default(space)))
    return is_notification_enabled(space, log.feature, log.channel)


def dispatch(space, row, message, now, tz):
    from apps.integrations.quiet_hours import quiet_until
    from apps.integrations.timing_dispatch import defer_log
    if row.kind.startswith('digest'):
        return _digest(space, row, now)
    kind, log_id, _due = row.subject.split(':', 2)
    model = EmailLog if kind == 'email' else NotificationDeliveryLog
    log = _logs(space, model).filter(pk=int(log_id), status='pending', error=f'deferred:{kind}:{_due}').first()
    if log is None:
        return NotificationResult(False)
    if quiet_until(space, 'email' if kind == 'email' else log.channel, now):
        defer_log(log, kind=kind, now=now)
        return NotificationResult(True)
    if not _allowed(log, space):
        log.status, log.error = 'skipped', 'notification_disabled_before_release'
        log.save(update_fields=['status', 'error', 'updated_at'])
        return NotificationResult(False)
    token = RELEASING.set(True)
    try:
        # The F1 claim is already committed. Re-use delivery-time suppression/module checks.
        if kind == 'email':
            from apps.integrations.dispatch import _deliver
            _deliver(log)
            channel = 'email'
        else:
            from apps.integrations.dispatch_channels import _deliver_notification
            _deliver_notification(log)
            channel = log.channel
        return NotificationResult(False, {channel: 1} if log.status == 'sent' else {},
                                  {channel: 1} if log.status == 'failed' else {})
    finally:
        RELEASING.reset(token)


def _digest(space, row, now):
    from apps.integrations.dispatch import dispatch_email
    from apps.integrations.quiet_hours import quiet_until
    from apps.integrations.timing_dispatch import defer_log
    _, user_id, due = row.subject.split(':', 2)
    queryset = _logs(space, EmailLog).filter(
        recipient_id=int(user_id), status='pending', error=f'deferred:digest:{due}',
    ).order_by('pk')
    if quiet_until(space, 'email', now):
        for log in queryset.iterator():
            defer_log(log, kind='email', now=now)
        return NotificationResult(True)
    groups = {}
    # Bound each batch. Tail gets its own reminder identity rather than disappearing.
    with transaction.atomic():
        for log in queryset.select_for_update()[:200]:
            allowed = _allowed(log, space)
            if allowed:
                # Preserve family and address boundaries so a queued summary can
                # still honour opt-outs and matrix changes at SMTP delivery time.
                from apps.notifications.preferences import STREAM_FEATURES
                family = log.feature or STREAM_FEATURES.get(log.stream, log.stream)
                groups.setdefault((family, log.to_email, log.audience), []).append(log)
            log.status = 'skipped'
            log.error = 'included_in_daily_digest' if allowed else 'notification_disabled_before_release'
            log.save(update_fields=['status', 'error', 'updated_at'])
        token = RELEASING.set(True)
        summaries = []
        try:
            for (family, address, audience), mails in groups.items():
                summaries.append(dispatch_email(
                    makerspace=space, to_email=address, recipient_id=int(user_id), feature=family,
                    subject=f'{space.name}: daily notification digest',
                    text_body='\n\n'.join(f'{mail.subject}\n{mail.text_body}' for mail in mails),
                    stream='notifications', event='daily_digest', audience=audience, sync=False,
                ))
        finally:
            RELEASING.reset(token)
        # A full batch may leave a tail; F1 identities are immutable after claims.
        remaining = list(queryset[:200])
        if remaining:
            from apps.operations.reminder_services import schedule_reminders
            schedule_reminders(makerspace=space, source='notifications.deferred',
                               subject=f'digest:{user_id}:{due}', kind=f'digest-tail-{remaining[0].pk}', due_at=now)
        queued = sum(summary.status not in {'failed', 'skipped'} for summary in summaries)
        failed = sum(summary.status == 'failed' for summary in summaries)
        return NotificationResult(False, {'email': queued} if queued else {},
                                  {'email': failed} if failed else {})


DEFERRED_SOURCE = ReminderSource('notifications.deferred', 'request_workflow', discover, build,
                                 dispatch=dispatch, requires_notifications=False)
