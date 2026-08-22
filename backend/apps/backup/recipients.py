"""Archive-recipient canonicalisation, custody proof, and lifecycle mutations."""

import base64
import binascii
import hashlib
import hmac
import secrets
import subprocess
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.audit import services as audit

from .custody import with_makerspace_custody_lock
from .models import ArchiveRecipientReservation, MakerspaceArchiveRecipient
from .recipient_states import (
    compromise_recipient,
    reactivate_recipient,
    revoke_recipient,
)
from .recipient_selection import selection_for
from .recipients_bech32 import Bech32DecodeError, convert_bits, decode, encode


__all__ = [
    "RecipientChallengeUnavailable",
    "canonical_recipient",
    "compromise_recipient",
    "enroll_recipient",
    "enroll_recipient_with_challenge",
    "encode_unpadded_base64url",
    "fingerprint_for",
    "reactivate_recipient",
    "reissue_recipient_challenge",
    "reserve_recipient",
    "revoke_recipient",
    "selection_for",
    "verify_recipient",
]


_RESERVED_MESSAGE = (
    "This key is already reserved on this deployment and cannot be reused."
)
_BECH32_MESSAGES = {
    "invalid_bech32": "The recipient is not valid Bech32.",
    "bech32m_checksum": "Bech32m recipients are not supported by age.",
    "invalid_checksum": "The recipient checksum is invalid.",
}
_CHALLENGE_INVALID = "The recipient challenge is invalid."


class RecipientChallengeUnavailable(RuntimeError):
    """Raised when age cannot produce a challenge ciphertext."""


def canonical_recipient(raw) -> str:
    """Validate and return the canonical lowercase native age recipient."""
    if not isinstance(raw, str):
        raise ValidationError("The recipient must be text.", code="recipient_type")

    value = raw.strip()
    if any(character.isspace() for character in value):
        raise ValidationError(
            "The recipient cannot contain internal whitespace.",
            code="recipient_whitespace",
        )
    if value.upper().startswith("AGE-SECRET-KEY"):
        raise ValidationError(
            "A private age identity cannot be used as a public recipient.",
            code="private_key",
        )

    if value == value.lower():
        value = value.lower()
    elif value == value.upper():
        value = value.lower()
    else:
        raise ValidationError(
            "Bech32 recipients cannot use mixed case.", code="mixed_case"
        )

    if value.startswith("age-plugin-"):
        raise ValidationError(
            "Plugin recipients are not supported.", code="plugin_recipient"
        )

    try:
        hrp, payload = decode(value)
    except Bech32DecodeError as exc:
        raise ValidationError(_BECH32_MESSAGES[exc.code], code=exc.code) from exc
    if hrp != "age":
        raise ValidationError(
            "The recipient must use the age human-readable prefix.",
            code="invalid_hrp",
        )
    decoded = convert_bits(payload, 5, 8, pad=False)
    if decoded is None or len(decoded) != 32:
        raise ValidationError(
            "The recipient payload must decode to 32 bytes.",
            code="invalid_payload_length",
        )
    return encode("age", convert_bits(decoded, 8, 5, pad=True))


def fingerprint_for(canonical: str) -> str:
    return hashlib.sha256(canonical.encode()).hexdigest()


@transaction.atomic
def enroll_recipient(*, makerspace, public_recipient, label, added_by=None):
    """Create an unverified recipient without claiming the permanent namespace."""
    canonical = canonical_recipient(public_recipient)
    fingerprint = fingerprint_for(canonical)
    if ArchiveRecipientReservation.objects.filter(fingerprint=fingerprint).exists():
        raise ValidationError(_RESERVED_MESSAGE, code="recipient_reserved")

    recipient = MakerspaceArchiveRecipient(
        makerspace=makerspace,
        public_recipient=canonical,
        fingerprint=fingerprint,
        label=label,
        added_by=added_by,
    )
    recipient.full_clean()
    recipient.save()
    return recipient


def reserve_recipient(recipient):
    """Permanently reserve one tenant recipient; verification will call this atomically."""
    try:
        with transaction.atomic():
            return ArchiveRecipientReservation.objects.create(
                fingerprint=recipient.fingerprint,
                makerspace_id_snapshot=recipient.makerspace_id,
                kind=ArchiveRecipientReservation.Kind.TENANT,
            )
    except IntegrityError as exc:
        if ArchiveRecipientReservation.objects.filter(
            fingerprint=recipient.fingerprint
        ).exists():
            raise ValidationError(
                _RESERVED_MESSAGE, code="recipient_reserved"
            ) from exc
        raise


def enroll_recipient_with_challenge(
    *, makerspace, public_recipient, label, added_by=None
):
    """Encrypt a fresh challenge, then atomically persist the recipient and digest."""
    canonical = canonical_recipient(public_recipient)
    raw_nonce, encrypted_challenge = _new_encrypted_challenge(canonical)
    with transaction.atomic():
        recipient = enroll_recipient(
            makerspace=makerspace,
            public_recipient=canonical,
            label=label,
            added_by=added_by,
        )
        recipient.challenge_nonce_digest = nonce_digest(raw_nonce)
        recipient.challenge_issued_at = timezone.now()
        recipient.save(
            update_fields=("challenge_nonce_digest", "challenge_issued_at")
        )
        _audit_recipient(added_by, "backup.archive_recipient_added", recipient)
    return recipient, encrypted_challenge


def verify_recipient(*, recipient_id, makerspace_id, submitted_nonce, actor=None):
    """Verify one canonical nonce and reserve its fingerprint in one locked commit."""
    raw_nonce = decode_submitted_nonce(submitted_nonce)
    with with_makerspace_custody_lock(makerspace_id) as custody:
        recipient = custody.recipient(recipient_id)
        if recipient.verified_at is not None:
            _refuse("This recipient is already verified.", "recipient_verified")
        if not recipient.challenge_nonce_digest or recipient.challenge_issued_at is None:
            _refuse("This recipient has no active challenge.", "challenge_missing")
        expires_at = recipient.challenge_issued_at + timedelta(
            seconds=settings.BACKUP_RECIPIENT_CHALLENGE_TTL_SECONDS
        )
        if timezone.now() >= expires_at:
            _refuse("This recipient challenge has expired.", "challenge_expired")
        if not hmac.compare_digest(
            recipient.challenge_nonce_digest, nonce_digest(raw_nonce)
        ):
            _refuse(_CHALLENGE_INVALID, "challenge_invalid")

        reserve_recipient(recipient)
        recipient.verified_at = timezone.now()
        recipient.challenge_nonce_digest = ""
        recipient.save(update_fields=("verified_at", "challenge_nonce_digest"))
        _audit_recipient(actor, "backup.archive_recipient_verified", recipient)
        return recipient


def reissue_recipient_challenge(*, recipient, actor=None):
    """Encrypt before taking the row lock, then replace the digest under that lock."""
    raw_nonce, encrypted_challenge = _new_encrypted_challenge(
        recipient.public_recipient
    )
    with transaction.atomic():
        locked = MakerspaceArchiveRecipient.objects.select_for_update().get(
            pk=recipient.pk, makerspace_id=recipient.makerspace_id
        )
        if locked.verified_at is not None:
            _refuse("A verified recipient cannot be reissued.", "recipient_verified")
        locked.challenge_nonce_digest = nonce_digest(raw_nonce)
        locked.challenge_issued_at = timezone.now()
        locked.save(
            update_fields=("challenge_nonce_digest", "challenge_issued_at")
        )
        _audit_recipient(
            actor, "backup.archive_recipient_challenge_reissued", locked
        )
        return locked, encrypted_challenge


def _new_encrypted_challenge(public_recipient):
    raw_nonce = secrets.token_bytes(32)
    exchanged_nonce = encode_unpadded_base64url(raw_nonce).encode("ascii")
    try:
        result = subprocess.run(
            ["age", "-r", public_recipient, "-o", "-"],
            input=exchanged_nonce,
            capture_output=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise RecipientChallengeUnavailable(
            "The recipient challenge could not be encrypted."
        ) from exc
    if not result.stdout:
        raise RecipientChallengeUnavailable(
            "The recipient challenge could not be encrypted."
        )
    return raw_nonce, encode_unpadded_base64url(result.stdout)


def decode_submitted_nonce(value):
    if not isinstance(value, str) or "=" in value:
        _refuse(_CHALLENGE_INVALID, "challenge_invalid")
    try:
        raw = base64.b64decode(
            value + ("=" * (-len(value) % 4)), altchars=b"-_", validate=True
        )
    except (ValueError, UnicodeEncodeError, binascii.Error) as exc:
        raise ValidationError(
            _CHALLENGE_INVALID, code="challenge_invalid"
        ) from exc
    if len(raw) != 32 or not hmac.compare_digest(
        encode_unpadded_base64url(raw), value
    ):
        _refuse(_CHALLENGE_INVALID, "challenge_invalid")
    return raw


def encode_unpadded_base64url(value):
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def nonce_digest(raw_nonce):
    return hashlib.sha256(raw_nonce).hexdigest()


def _audit_recipient(actor, action, recipient):
    audit.record(
        actor,
        action,
        makerspace=recipient.makerspace,
        target=recipient,
        meta={"recipient_id": recipient.pk, "fingerprint": recipient.fingerprint},
    )


def _refuse(message, code):
    raise ValidationError(message, code=code)
