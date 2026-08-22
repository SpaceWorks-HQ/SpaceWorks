"""Short, makerspace-first transactions for archive-recipient state changes."""

from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.audit import services as audit

from .custody import (
    RECIPIENT_COMPROMISED,
    RECIPIENT_FLOOR,
    with_makerspace_custody_lock,
)


def revoke_recipient(*, recipient, actor=None):
    with with_makerspace_custody_lock(recipient.makerspace_id) as custody:
        locked = custody.recipient(recipient.pk)
        if (
            _is_effective(locked)
            and custody.verified_recipient_count() <= RECIPIENT_FLOOR
        ):
            raise ValidationError(
                "At least two verified archive recipients must remain active.",
                code="recipient_floor",
            )
        locked.revoked_at = timezone.now()
        locked.save(update_fields=("revoked_at",))
        _audit_recipient(actor, "backup.archive_recipient_revoked", locked)
        return locked


def compromise_recipient(*, recipient, actor=None):
    with with_makerspace_custody_lock(recipient.makerspace_id) as custody:
        locked = custody.recipient(recipient.pk)
        was_effective = _is_effective(locked)
        locked.compromised_at = timezone.now()
        locked.save(update_fields=("compromised_at",))
        if was_effective:
            custody.record_trigger(
                reason_code=RECIPIENT_COMPROMISED,
                recipient=locked,
            )
        _audit_recipient(actor, "backup.archive_recipient_compromised", locked)
        return locked


def reactivate_recipient(*, recipient, actor=None):
    with with_makerspace_custody_lock(recipient.makerspace_id) as custody:
        locked = custody.recipient(recipient.pk)
        if locked.compromised_at is not None:
            raise ValidationError(
                "A compromised recipient cannot be reactivated.",
                code="recipient_compromised",
            )
        if locked.revoked_at is None:
            raise ValidationError(
                "This recipient is not revoked.", code="recipient_not_revoked"
            )
        locked.revoked_at = None
        locked.save(update_fields=("revoked_at",))
        _audit_recipient(
            actor, "backup.archive_recipient_reactivated", locked
        )
        return locked


def _is_effective(recipient):
    return (
        recipient.verified_at is not None
        and recipient.revoked_at is None
        and recipient.compromised_at is None
    )


def _audit_recipient(actor, action, recipient):
    audit.record(
        actor,
        action,
        makerspace=recipient.makerspace,
        target=recipient,
        meta={"recipient_id": recipient.pk, "fingerprint": recipient.fingerprint},
    )
