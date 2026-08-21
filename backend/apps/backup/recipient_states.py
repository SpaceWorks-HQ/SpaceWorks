"""Lock-free, short transactions for urgent archive-recipient state changes."""

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.audit import services as audit

from .models import MakerspaceArchiveRecipient


def revoke_recipient(*, recipient, actor=None):
    return _set_recipient_state(
        recipient=recipient,
        actor=actor,
        action="backup.archive_recipient_revoked",
        updates={"revoked_at": timezone.now()},
    )


def compromise_recipient(*, recipient, actor=None):
    return _set_recipient_state(
        recipient=recipient,
        actor=actor,
        action="backup.archive_recipient_compromised",
        updates={"compromised_at": timezone.now()},
    )


def reactivate_recipient(*, recipient, actor=None):
    with transaction.atomic():
        updated = MakerspaceArchiveRecipient.objects.filter(
            pk=recipient.pk,
            makerspace_id=recipient.makerspace_id,
            compromised_at__isnull=True,
            revoked_at__isnull=False,
        ).update(revoked_at=None)
        if not updated:
            current = MakerspaceArchiveRecipient.objects.get(pk=recipient.pk)
            if current.compromised_at is not None:
                raise ValidationError(
                    "A compromised recipient cannot be reactivated.",
                    code="recipient_compromised",
                )
            raise ValidationError(
                "This recipient is not revoked.", code="recipient_not_revoked"
            )
        recipient.refresh_from_db()
        _audit_recipient(
            actor, "backup.archive_recipient_reactivated", recipient
        )
        return recipient


def _set_recipient_state(*, recipient, actor, action, updates):
    with transaction.atomic():
        MakerspaceArchiveRecipient.objects.filter(
            pk=recipient.pk, makerspace_id=recipient.makerspace_id
        ).update(**updates)
        recipient.refresh_from_db()
        _audit_recipient(actor, action, recipient)
        return recipient


def _audit_recipient(actor, action, recipient):
    audit.record(
        actor,
        action,
        makerspace=recipient.makerspace,
        target=recipient,
        meta={"recipient_id": recipient.pk, "fingerprint": recipient.fingerprint},
    )
