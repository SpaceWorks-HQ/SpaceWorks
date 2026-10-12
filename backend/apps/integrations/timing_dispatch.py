"""Persist delayed sends in the existing outboxes and let F1 claim them once."""

import logging
from contextvars import ContextVar

from django.db import transaction
from django.utils import timezone

from apps.integrations.dispatch_policy import never_deferred
from apps.integrations.quiet_hours import quiet_until

logger = logging.getLogger(__name__)
RELEASING = ContextVar('notification_timing_release', default=False)


def defer_log(log, *, kind, now=None):
    # Redacted sync-only bodies may contain live credentials. They cannot be
    # reconstructed from an outbox row and must never enter a deferred digest.
    if getattr(log, '_timing_ineligible', False):
        return False
    if RELEASING.get() or not log.makerspace_id or never_deferred(log.stream if kind == 'email' else log.feature, log.event):
        return False
    try:
        now = now or timezone.now()
        until = quiet_until(log.makerspace, 'email' if kind == 'email' else log.channel, now)
        digest = None
        if kind == 'email' and log.event != 'daily_digest':
            from apps.integrations.digests import digest_due
            digest = digest_due(log.makerspace, log.recipient_id, log.feature, now)
            if digest:
                until = max(until, digest) if until else digest
                until = quiet_until(log.makerspace, 'email', until) or until
        if until is None:
            return False
        from apps.operations.reminder_services import schedule_reminders
        marker = 'digest' if digest else kind
        subject = f'digest:{log.recipient_id}:{until.isoformat()}' if digest else f'{kind}:{log.pk}:{until.isoformat()}'
        # Schedule inside the outbox transaction; a failed insert must not leave a
        # PENDING row stranded with no reminder to release it.
        with transaction.atomic():
            schedule_reminders(makerspace=log.makerspace, source='notifications.deferred',
                               subject=subject, kind=marker, due_at=until)
            log.error = f'deferred:{marker}:{until.isoformat()}'
            log.status = 'pending'
            log.save(update_fields=['error', 'status', 'updated_at'])
        return True
    except Exception:
        logger.warning('notification_timing_failed_open', extra={'makerspace_id': log.makerspace_id})
        return False
