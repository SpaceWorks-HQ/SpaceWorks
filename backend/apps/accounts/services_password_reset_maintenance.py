"""Non-worker expiry transitions for password-reset envelopes."""

from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone

from apps.accounts.models import PasswordResetEnvelope, PasswordResetEnvelopeStatus
from apps.accounts.password_reset_crypto import new_dummy_digest
from apps.accounts.services_password_reset import MAX_ATTEMPTS

DEFAULT_BATCH_SIZE = 50


def expire_delivery_leases(*, batch_size=DEFAULT_BATCH_SIZE, now=None):
    """Fence uncertain SMTP outcomes terminally; never reclaim or re-send them."""
    expired_at = now or timezone.now()
    with transaction.atomic():
        rows = list(
            PasswordResetEnvelope.objects.select_for_update(skip_locked=True)
            .filter(
                status=PasswordResetEnvelopeStatus.DELIVERING,
                claim_expires_at__lte=expired_at,
            )
            .order_by("claim_expires_at", "pk")[:batch_size]
        )
        changed = 0
        for row in rows:
            # Generation advances in the SAME statement as the terminal transition.
            # A worker returning from an uncertain SMTP call can therefore never
            # overwrite delivery_unknown with its stale finalization.
            changed += PasswordResetEnvelope.objects.filter(
                pk=row.pk,
                generation=row.generation,
                status=PasswordResetEnvelopeStatus.DELIVERING,
                claim_expires_at__lte=expired_at,
            ).update(
                status=PasswordResetEnvelopeStatus.DELIVERY_UNKNOWN,
                digest=new_dummy_digest(row.email_normalized),
                digest_is_live=False,
                credential_fingerprint="",
                expires_at=None,
                terminal_at=expired_at,
                claimed_at=None,
                claim_owner="",
                claim_expires_at=None,
                generation=F("generation") + 1,
            )
    return changed


def discard_expired_issued(*, batch_size=DEFAULT_BATCH_SIZE, now=None):
    """Make expired or attempt-exhausted challenges terminal off the request path."""
    expired_at = now or timezone.now()
    with transaction.atomic():
        rows = list(
            PasswordResetEnvelope.objects.select_for_update(skip_locked=True)
            .filter(status=PasswordResetEnvelopeStatus.ISSUED)
            .filter(
                Q(expires_at__lte=expired_at)
                | Q(attempts__gte=MAX_ATTEMPTS)
            )
            .order_by("expires_at", "pk")[:batch_size]
        )
        changed = 0
        for row in rows:
            changed += PasswordResetEnvelope.objects.filter(
                pk=row.pk,
                generation=row.generation,
                status=PasswordResetEnvelopeStatus.ISSUED,
            ).update(
                status=PasswordResetEnvelopeStatus.DISCARDED,
                digest=new_dummy_digest(row.email_normalized),
                digest_is_live=False,
                credential_fingerprint="",
                expires_at=None,
                terminal_at=expired_at,
            )
    return changed
