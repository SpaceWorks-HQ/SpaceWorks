"""Lease-fenced, at-most-once issuance drain for password reset envelopes."""

import logging
import os
import socket
import uuid
from dataclasses import dataclass
from datetime import timedelta

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.accounts.models import PasswordResetEnvelope, PasswordResetEnvelopeStatus, User
from apps.accounts.password_reset_crypto import (
    credential_fingerprint,
    generate_otp,
    new_dummy_digest,
    otp_digest,
)
from apps.accounts.services_password_reset_maintenance import (
    discard_expired_issued,
    expire_delivery_leases,
)
from apps.integrations.email import email_enabled, send_password_reset_otp

logger = logging.getLogger(__name__)

CHALLENGE_TTL = timedelta(minutes=10)
CLAIM_LEASE = timedelta(minutes=5)
DEFAULT_BATCH_SIZE = 50


@dataclass(frozen=True)
class EnvelopeClaim:
    envelope_id: int
    generation: int
    email_normalized: str


@dataclass(frozen=True)
class DeliveryAttempt:
    claim: EnvelopeClaim
    recipient: str
    code: str


def drain_password_reset_envelopes(*, batch_size=DEFAULT_BATCH_SIZE, owner=None):
    """Resolve, mint and synchronously deliver one bounded claimed batch."""
    expire_delivery_leases(batch_size=batch_size)
    discard_expired_issued(batch_size=batch_size)
    claims = claim_pending_envelopes(batch_size=batch_size, owner=owner)
    outcomes = {"claimed": len(claims), "issued": 0, "terminal": 0, "stale": 0}
    for claim in claims:
        attempt = prepare_delivery(claim)
        if attempt is None:
            outcomes["stale"] += 1
            continue
        if isinstance(attempt, str):
            outcomes["terminal"] += 1
            continue
        delivered = False
        try:
            # The digest and `delivering` state committed before this SMTP call. This
            # call must remain synchronous and outside every row-lock transaction.
            delivered = bool(
                send_password_reset_otp(
                    attempt.recipient,
                    attempt.code,
                    expires_in_minutes=int(CHALLENGE_TTL.total_seconds() // 60),
                )
            )
        except Exception:  # provider failure is terminal but never crashes the drain
            logger.exception(
                "password_reset_delivery_failed",
                extra={"envelope_id": claim.envelope_id},
            )
        if finalize_delivery(claim, delivered=delivered):
            outcomes["issued" if delivered else "terminal"] += 1
        else:
            outcomes["stale"] += 1
    logger.info("password_reset_drain_complete", extra=outcomes)
    return outcomes


def claim_pending_envelopes(*, batch_size=DEFAULT_BATCH_SIZE, owner=None, now=None):
    claimed_at = now or timezone.now()
    claim_owner = (owner or _worker_identity())[:128]
    with transaction.atomic():
        rows = list(
            PasswordResetEnvelope.objects.select_for_update(skip_locked=True)
            .filter(
                Q(status=PasswordResetEnvelopeStatus.PENDING)
                | Q(
                    status=PasswordResetEnvelopeStatus.CLAIMED,
                    claim_expires_at__lte=claimed_at,
                )
            )
            .order_by("requested_at", "pk")[:batch_size]
        )
        claims = []
        for row in rows:
            row.status = PasswordResetEnvelopeStatus.CLAIMED
            row.claimed_at = claimed_at
            row.claim_owner = claim_owner
            row.claim_expires_at = claimed_at + CLAIM_LEASE
            row.generation += 1
            row.save(
                update_fields=[
                    "status",
                    "claimed_at",
                    "claim_owner",
                    "claim_expires_at",
                    "generation",
                ]
            )
            claims.append(
                EnvelopeClaim(row.pk, row.generation, row.email_normalized)
            )
    return claims


def prepare_delivery(claim, *, now=None):
    """Commit the digest and delivering state, returning the in-memory secret."""
    issued_at = now or timezone.now()
    with transaction.atomic():
        envelope = (
            PasswordResetEnvelope.objects.select_for_update()
            .filter(
                pk=claim.envelope_id,
                generation=claim.generation,
                status=PasswordResetEnvelopeStatus.CLAIMED,
            )
            .first()
        )
        if envelope is None:
            return None
        # Envelope -> User is the declared lock order shared with confirmation.
        user = (
            User.objects.select_for_update()
            .filter(email__iexact=envelope.email_normalized)
            .first()
        )
        if not _recoverable(user):
            return _finish_claimed_terminal(
                envelope, claim, PasswordResetEnvelopeStatus.DISCARDED, issued_at
            )
        # Availability is re-checked where issuance actually occurs. The deployment-level
        # request-time gate alone is insufficient because configuration may change in queue.
        if not email_enabled():
            return _finish_claimed_terminal(
                envelope, claim, PasswordResetEnvelopeStatus.UNDELIVERABLE, issued_at
            )

        code = generate_otp()
        updated = PasswordResetEnvelope.objects.filter(
            pk=envelope.pk,
            generation=claim.generation,
            status=PasswordResetEnvelopeStatus.CLAIMED,
        ).update(
            user=user,
            digest=otp_digest(code, envelope.email_normalized),
            digest_is_live=True,
            credential_fingerprint=credential_fingerprint(
                user, envelope.email_normalized
            ),
            expires_at=issued_at + CHALLENGE_TTL,
            consumed_at=None,
            attempts=0,
            status=PasswordResetEnvelopeStatus.DELIVERING,
            claim_expires_at=issued_at + CLAIM_LEASE,
            terminal_at=None,
            superseded_at=None,
        )
        if updated != 1:
            return None
    return DeliveryAttempt(claim, envelope.email_normalized, code)


def finalize_delivery(claim, *, delivered, now=None):
    """Fence the SMTP result against lease expiry or a newer claim generation."""
    finished_at = now or timezone.now()
    filters = {
        "pk": claim.envelope_id,
        "generation": claim.generation,
        "status": PasswordResetEnvelopeStatus.DELIVERING,
    }
    if delivered:
        updated = PasswordResetEnvelope.objects.filter(**filters).update(
            status=PasswordResetEnvelopeStatus.ISSUED,
            claimed_at=None,
            claim_owner="",
            claim_expires_at=None,
        )
    else:
        updated = PasswordResetEnvelope.objects.filter(**filters).update(
            status=PasswordResetEnvelopeStatus.UNDELIVERABLE,
            digest=new_dummy_digest(claim.email_normalized),
            digest_is_live=False,
            credential_fingerprint="",
            expires_at=None,
            terminal_at=finished_at,
            claimed_at=None,
            claim_owner="",
            claim_expires_at=None,
        )
    return updated == 1


def _finish_claimed_terminal(envelope, claim, status, now):
    updated = PasswordResetEnvelope.objects.filter(
        pk=envelope.pk,
        generation=claim.generation,
        status=PasswordResetEnvelopeStatus.CLAIMED,
    ).update(
        status=status,
        user=None,
        digest=new_dummy_digest(envelope.email_normalized),
        digest_is_live=False,
        credential_fingerprint="",
        expires_at=None,
        terminal_at=now,
        claimed_at=None,
        claim_owner="",
        claim_expires_at=None,
    )
    return status if updated == 1 else None


def _recoverable(user):
    return bool(
        user is not None
        and user.is_active
        and user.access_status == User.AccessStatus.ACTIVE
        and not user.is_walk_in
    )


def _worker_identity():
    return f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex}"
