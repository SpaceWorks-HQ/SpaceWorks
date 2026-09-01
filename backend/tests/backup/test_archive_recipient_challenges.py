import base64
import hashlib
from datetime import timedelta
from types import SimpleNamespace

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.backup.models import (
    ArchiveRecipientReservation,
    MakerspaceArchiveRecipient,
)
from apps.backup.recipients import (
    encode_unpadded_base64url,
    enroll_recipient,
    enroll_recipient_with_challenge,
    reissue_recipient_challenge,
    verify_recipient,
)
from apps.makerspaces.models import Makerspace


pytestmark = pytest.mark.django_db

VALID_RECIPIENT = (
    "age1qqqsyqcyq5rqwzqfpg9scrgwpugpzysnzs23v9ccrydpk8qarc0savhh7m"
)
RAW_NONCE = bytes(range(32))
OTHER_NONCE = bytes(range(32, 64))


def _fake_age(monkeypatch, nonces=(RAW_NONCE,)):
    calls = []
    values = iter(nonces)
    monkeypatch.setattr(
        "apps.backup.recipients.secrets.token_bytes",
        lambda size: next(values) if size == 32 else None,
    )

    def run(args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(stdout=b"age ciphertext")

    monkeypatch.setattr("apps.backup.recipients.subprocess.run", run)
    return calls


def _challenged(makerspace, raw=RAW_NONCE):
    recipient = enroll_recipient(
        makerspace=makerspace,
        public_recipient=VALID_RECIPIENT,
        label="Custody label",
    )
    recipient.challenge_nonce_digest = hashlib.sha256(raw).hexdigest()
    recipient.challenge_issued_at = timezone.now()
    recipient.save(
        update_fields=("challenge_nonce_digest", "challenge_issued_at")
    )
    return recipient


def _verify(recipient, raw=RAW_NONCE):
    return verify_recipient(
        recipient_id=recipient.pk,
        makerspace_id=recipient.makerspace_id,
        submitted_nonce=encode_unpadded_base64url(raw),
    )


def test_correct_nonce_verifies_reserves_clears_digest_and_replay_refuses():
    makerspace = Makerspace.objects.create(name="Proof", slug="proof")
    recipient = _challenged(makerspace)

    _verify(recipient)
    recipient.refresh_from_db()

    assert recipient.verified_at is not None
    assert recipient.challenge_nonce_digest == ""
    assert ArchiveRecipientReservation.objects.filter(
        fingerprint=recipient.fingerprint,
        makerspace_id_snapshot=makerspace.pk,
    ).exists()
    with pytest.raises(ValidationError):
        _verify(recipient)
    assert ArchiveRecipientReservation.objects.filter(
        fingerprint=recipient.fingerprint
    ).count() == 1


@pytest.mark.parametrize("case", ("wrong", "expired", "verified"))
def test_invalid_lifecycle_attempts_refuse_without_reserving(case, settings):
    makerspace = Makerspace.objects.create(name=case, slug=f"challenge-{case}")
    recipient = _challenged(makerspace)
    submitted = OTHER_NONCE if case == "wrong" else RAW_NONCE
    if case == "expired":
        settings.BACKUP_RECIPIENT_CHALLENGE_TTL_SECONDS = 60
        recipient.challenge_issued_at = timezone.now() - timedelta(seconds=61)
        recipient.save(update_fields=("challenge_issued_at",))
    if case == "verified":
        recipient.verified_at = timezone.now()
        recipient.save(update_fields=("verified_at",))

    with pytest.raises(ValidationError):
        _verify(recipient, submitted)

    recipient.refresh_from_db()
    assert ArchiveRecipientReservation.objects.filter(
        fingerprint=recipient.fingerprint
    ).count() == 0
    assert recipient.challenge_nonce_digest


def test_padded_nonce_is_refused():
    makerspace = Makerspace.objects.create(name="Padded", slug="padded")
    recipient = _challenged(makerspace)
    with pytest.raises(ValidationError):
        verify_recipient(
            recipient_id=recipient.pk,
            makerspace_id=makerspace.pk,
            submitted_nonce=encode_unpadded_base64url(RAW_NONCE) + "=",
        )
    assert not ArchiveRecipientReservation.objects.filter(
        fingerprint=recipient.fingerprint
    ).exists()


def test_noncanonical_base64url_nonce_is_refused():
    makerspace = Makerspace.objects.create(name="Noncanonical", slug="noncanonical")
    recipient = _challenged(makerspace)
    canonical = encode_unpadded_base64url(RAW_NONCE)
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
    final_index = alphabet.index(canonical[-1])
    noncanonical = canonical[:-1] + alphabet[final_index + 1]
    assert base64.urlsafe_b64decode(noncanonical + "=") == RAW_NONCE

    with pytest.raises(ValidationError):
        verify_recipient(
            recipient_id=recipient.pk,
            makerspace_id=makerspace.pk,
            submitted_nonce=noncanonical,
        )
    assert not ArchiveRecipientReservation.objects.filter(
        fingerprint=recipient.fingerprint
    ).exists()


def test_nonce_decoding_to_wrong_length_is_refused():
    makerspace = Makerspace.objects.create(name="Short", slug="short-nonce")
    recipient = _challenged(makerspace)
    with pytest.raises(ValidationError):
        verify_recipient(
            recipient_id=recipient.pk,
            makerspace_id=makerspace.pk,
            submitted_nonce=encode_unpadded_base64url(RAW_NONCE[:-1]),
        )
    assert not ArchiveRecipientReservation.objects.filter(
        fingerprint=recipient.fingerprint
    ).exists()


def test_reissue_replaces_digest_and_old_nonce_no_longer_verifies(monkeypatch):
    makerspace = Makerspace.objects.create(name="Reissue", slug="reissue")
    _fake_age(monkeypatch, (RAW_NONCE, OTHER_NONCE, RAW_NONCE))
    recipient, _ = enroll_recipient_with_challenge(
        makerspace=makerspace,
        public_recipient=VALID_RECIPIENT,
        label="Reissue test",
    )
    recipient, _ = reissue_recipient_challenge(recipient=recipient)

    with pytest.raises(ValidationError):
        _verify(recipient, RAW_NONCE)
    _verify(recipient, OTHER_NONCE)
    with pytest.raises(ValidationError):
        reissue_recipient_challenge(recipient=recipient)


def test_reservation_collision_rolls_back_verification(monkeypatch):
    makerspace = Makerspace.objects.create(name="Collision", slug="collision")
    other = Makerspace.objects.create(name="Other", slug="collision-other")
    _fake_age(monkeypatch)
    recipient, _ = enroll_recipient_with_challenge(
        makerspace=makerspace,
        public_recipient=VALID_RECIPIENT,
        label="Collision test",
    )
    existing = ArchiveRecipientReservation.objects.create(
        fingerprint=recipient.fingerprint,
        makerspace_id_snapshot=other.pk,
        kind=ArchiveRecipientReservation.Kind.TENANT,
    )

    with pytest.raises(ValidationError):
        _verify(recipient)

    recipient.refresh_from_db()
    assert recipient.verified_at is None
    assert recipient.challenge_nonce_digest == hashlib.sha256(RAW_NONCE).hexdigest()
    assert list(
        ArchiveRecipientReservation.objects.filter(
            fingerprint=recipient.fingerprint
        ).values_list("pk", flat=True)
    ) == [existing.pk]


def test_age_receives_only_base64url_nonce_on_stdin(monkeypatch):
    makerspace = Makerspace.objects.create(name="Stdin", slug="stdin")
    calls = _fake_age(monkeypatch)

    enroll_recipient_with_challenge(
        makerspace=makerspace,
        public_recipient=VALID_RECIPIENT,
        label="Do not leak nonce",
    )

    args, kwargs = calls[0]
    exchanged = encode_unpadded_base64url(RAW_NONCE).encode("ascii")
    assert args == ["age", "-r", VALID_RECIPIENT, "-o", "-"]
    assert kwargs == {
        "input": exchanged,
        "capture_output": True,
        "check": True,
    }
    assert all(exchanged not in str(argument).encode() for argument in args)
