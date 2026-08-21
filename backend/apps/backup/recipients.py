"""Canonical native age recipients and their deployment-wide reservation boundary."""

import hashlib

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from .models import ArchiveRecipientReservation, MakerspaceArchiveRecipient
from .recipients_bech32 import Bech32DecodeError, convert_bits, decode, encode


_RESERVED_MESSAGE = (
    "This key is already reserved on this deployment and cannot be reused."
)
_BECH32_MESSAGES = {
    "invalid_bech32": "The recipient is not valid Bech32.",
    "bech32m_checksum": "Bech32m recipients are not supported by age.",
    "invalid_checksum": "The recipient checksum is invalid.",
}


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
