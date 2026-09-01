import pytest
from django.core.exceptions import ValidationError
from django.db import DatabaseError, IntegrityError, transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.backup.models import (
    ArchiveRecipientReservation,
    MakerspaceArchiveRecipient,
)
from apps.backup.recipients import (
    canonical_recipient,
    enroll_recipient,
    fingerprint_for,
    reserve_recipient,
)
from apps.makerspaces import lifecycle
from apps.makerspaces.models import Makerspace


VALID_RECIPIENT = (
    "age1qqqsyqcyq5rqwzqfpg9scrgwpugpzysnzs23v9ccrydpk8qarc0savhh7m"
)
BECH32M_RECIPIENT = (
    "age1qqqsyqcyq5rqwzqfpg9scrgwpugpzysnzs23v9ccrydpk8qarc0sgs8mme"
)
WRONG_HRP_RECIPIENT = (
    "foo1qqqsyqcyq5rqwzqfpg9scrgwpugpzysnzs23v9ccrydpk8qarc0sthlvw8"
)
SHORT_PAYLOAD_RECIPIENT = (
    "age1qqqsyqcyq5rqwzqfpg9scrgwpugpzysnzs23v9ccrydpk8qarc535lh4"
)


def _code(raw):
    with pytest.raises(ValidationError) as caught:
        canonical_recipient(raw)
    return caught.value.code


def test_canonical_recipient_rejects_internal_whitespace_with_own_code():
    assert _code(f"{VALID_RECIPIENT[:12]} {VALID_RECIPIENT[12:]}") == (
        "recipient_whitespace"
    )


def test_canonical_recipient_rejects_private_key_prefix_without_echoing_input():
    private = "AGE-SECRET-KEY-1DO-NOT-ECHO"
    with pytest.raises(ValidationError) as caught:
        canonical_recipient(private)

    assert caught.value.code == "private_key"
    assert private not in str(caught.value)


def test_canonical_recipient_rejects_mixed_case_with_own_code():
    mixed = "A" + VALID_RECIPIENT[1:]
    assert _code(mixed) == "mixed_case"


def test_canonical_recipient_rejects_bad_checksum_with_own_code():
    replacement = "q" if VALID_RECIPIENT[-1] != "q" else "p"
    assert _code(VALID_RECIPIENT[:-1] + replacement) == "invalid_checksum"


def test_canonical_recipient_rejects_bech32m_checksum_with_own_code():
    assert _code(BECH32M_RECIPIENT) == "bech32m_checksum"


def test_canonical_recipient_rejects_wrong_hrp_with_own_code():
    assert _code(WRONG_HRP_RECIPIENT) == "invalid_hrp"


def test_canonical_recipient_rejects_non_32_byte_payload_with_own_code():
    assert _code(SHORT_PAYLOAD_RECIPIENT) == "invalid_payload_length"


def test_canonical_recipient_rejects_plugin_form_with_own_code():
    assert _code("age-plugin-example1nativeonly") == "plugin_recipient"


@pytest.mark.django_db
def test_uppercase_recipient_is_stored_lowercase_and_reserved_form_cannot_reenter():
    makerspace = Makerspace.objects.create(name="Uppercase", slug="uppercase-recipient")
    recipient = enroll_recipient(
        makerspace=makerspace,
        public_recipient=VALID_RECIPIENT.upper(),
        label="Offline custody",
    )
    reserve_recipient(recipient)

    assert recipient.public_recipient == VALID_RECIPIENT
    assert recipient.fingerprint == fingerprint_for(VALID_RECIPIENT)
    with pytest.raises(ValidationError) as caught:
        enroll_recipient(
            makerspace=makerspace,
            public_recipient=VALID_RECIPIENT,
            label="Duplicate",
        )
    assert caught.value.code == "recipient_reserved"


@pytest.mark.django_db(transaction=True)
def test_reservation_is_global_and_survives_real_makerspace_purge(monkeypatch):
    actor = User.objects.create_superuser(
        username="archive-reservation-purge",
        email="archive-reservation-purge@example.test",
        password="password",
    )
    first = Makerspace.objects.create(name="First", slug="recipient-first")
    second = Makerspace.objects.create(name="Second", slug="recipient-second")
    recipient = enroll_recipient(
        makerspace=first,
        public_recipient=VALID_RECIPIENT,
        label="Permanent namespace",
        added_by=actor,
    )
    second_recipient = enroll_recipient(
        makerspace=second,
        public_recipient=VALID_RECIPIENT,
        label="Pending cross-tenant proof",
        added_by=actor,
    )
    reservation = reserve_recipient(recipient)

    with pytest.raises(ValidationError) as caught:
        reserve_recipient(second_recipient)
    assert caught.value.code == "recipient_reserved"

    first.archived_at = timezone.now()
    first.archived_by = actor
    first.save(update_fields=("archived_at", "archived_by"))
    monkeypatch.setattr(lifecycle, "_delete_storage_keys", lambda keys: None)
    monkeypatch.setattr(lifecycle, "_delete_public_image_keys", lambda keys: None)
    lifecycle.purge(first, actor)

    assert not Makerspace.objects.filter(pk=first.pk).exists()
    assert not MakerspaceArchiveRecipient.objects.filter(pk=recipient.pk).exists()
    assert ArchiveRecipientReservation.objects.filter(pk=reservation.pk).exists()
    with pytest.raises(ValidationError) as caught:
        reserve_recipient(second_recipient)
    assert caught.value.code == "recipient_reserved"
    with pytest.raises(ValidationError) as caught:
        enroll_recipient(
            makerspace=second,
            public_recipient=VALID_RECIPIENT,
            label="Reuse after purge",
            added_by=actor,
        )
    assert caught.value.code == "recipient_reserved"


@pytest.mark.django_db(transaction=True)
def test_reservation_trigger_rejects_orm_update_and_delete():
    makerspace = Makerspace.objects.create(name="Immutable", slug="recipient-immutable")
    reservation = reserve_recipient(
        enroll_recipient(
            makerspace=makerspace,
            public_recipient=VALID_RECIPIENT,
            label="Immutable",
        )
    )

    with pytest.raises(DatabaseError), transaction.atomic():
        ArchiveRecipientReservation.objects.filter(pk=reservation.pk).update(
            fingerprint="f" * 64
        )
    with pytest.raises(DatabaseError), transaction.atomic():
        ArchiveRecipientReservation.objects.filter(pk=reservation.pk).delete()

    reservation.refresh_from_db()
    assert reservation.fingerprint == fingerprint_for(VALID_RECIPIENT)


@pytest.mark.django_db
def test_reservation_constraint_rejects_tenant_without_snapshot():
    with pytest.raises(IntegrityError), transaction.atomic():
        ArchiveRecipientReservation.objects.create(
            fingerprint="a" * 64,
            makerspace_id_snapshot=None,
            kind=ArchiveRecipientReservation.Kind.TENANT,
        )


@pytest.mark.django_db
def test_reservation_constraint_rejects_platform_with_snapshot():
    with pytest.raises(IntegrityError), transaction.atomic():
        ArchiveRecipientReservation.objects.create(
            fingerprint="b" * 64,
            makerspace_id_snapshot=42,
            kind=ArchiveRecipientReservation.Kind.PLATFORM,
        )
