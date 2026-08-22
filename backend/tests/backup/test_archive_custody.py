import hashlib

import pytest
from django.core.exceptions import ValidationError
from django.db import connection, transaction
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.backup.custody import RECIPIENT_COMPROMISED
from apps.backup.models import (
    MakerspaceArchiveCustodyState,
    MakerspaceArchiveRecipient,
)
from apps.backup.recipient_states import (
    compromise_recipient,
    reactivate_recipient,
    revoke_recipient,
)
from apps.backup.recipients import encode_unpadded_base64url, verify_recipient
from apps.makerspaces.models import Makerspace


pytestmark = pytest.mark.django_db
NONCE = bytes(range(32))


def _recipient(makerspace, number, *, verified=True, revoked=False):
    return MakerspaceArchiveRecipient.objects.create(
        makerspace=makerspace,
        public_recipient=f"age1custodytest{number}",
        fingerprint=f"{number:064x}",
        label=f"Custodian {number}",
        verified_at=timezone.now() if verified else None,
        revoked_at=timezone.now() if revoked else None,
    )


def _degraded_state(makerspace):
    return MakerspaceArchiveCustodyState.objects.create(
        makerspace=makerspace,
        state=MakerspaceArchiveCustodyState.State.DEGRADED_ONE_RECIPIENT,
        reason_code=RECIPIENT_COMPROMISED,
        alarm_episode=1,
        last_alarm_at=timezone.now(),
    )


def _assert_makerspace_lock_precedes_recipient_locks(queries):
    statements = [query["sql"] for query in queries]
    makerspace_lock = next(
        index
        for index, sql in enumerate(statements)
        if 'FROM "makerspaces_makerspace"' in sql and "FOR UPDATE" in sql
    )
    recipient_lock = next(
        index
        for index, sql in enumerate(statements)
        if 'FROM "backup_makerspacearchiverecipient"' in sql
        and "FOR UPDATE" in sql
    )
    assert makerspace_lock < recipient_lock


def test_ordinary_revocation_from_two_to_one_is_refused():
    makerspace = Makerspace.objects.create(name="Floor", slug="custody-floor")
    recipient = _recipient(makerspace, 1)
    _recipient(makerspace, 2)

    with pytest.raises(ValidationError) as caught:
        revoke_recipient(recipient=recipient)

    recipient.refresh_from_db()
    assert caught.value.code == "recipient_floor"
    assert "two verified archive recipients" in str(caught.value)
    assert recipient.revoked_at is None
    assert not MakerspaceArchiveCustodyState.objects.filter(
        makerspace=makerspace
    ).exists()


def test_compromise_from_two_to_one_succeeds_and_records_degraded_state():
    makerspace = Makerspace.objects.create(
        name="Degraded",
        slug="custody-degraded",
        superadmin_access_enabled=False,
    )
    recipient = _recipient(makerspace, 10)
    other = _recipient(makerspace, 11)

    compromise_recipient(recipient=recipient)

    recipient.refresh_from_db()
    makerspace.refresh_from_db()
    state = MakerspaceArchiveCustodyState.objects.get(makerspace=makerspace)
    assert recipient.compromised_at is not None
    assert state.state == state.State.DEGRADED_ONE_RECIPIENT
    assert state.reason_code == RECIPIENT_COMPROMISED
    assert state.triggering_recipient == recipient
    assert state.alarm_episode == 1
    assert makerspace.superadmin_access_enabled is False
    assert set(makerspace.archive_recipients.values_list("pk", flat=True)) == {
        recipient.pk,
        other.pk,
    }


def test_compromise_to_zero_records_floor_breach():
    makerspace = Makerspace.objects.create(
        name="Zero", slug="custody-zero", superadmin_access_enabled=False
    )
    recipient = _recipient(makerspace, 20)

    compromise_recipient(recipient=recipient)

    state = MakerspaceArchiveCustodyState.objects.get(makerspace=makerspace)
    assert state.state == state.State.FLOOR_BREACHED_ZERO
    assert state.reason_code == RECIPIENT_COMPROMISED
    assert state.triggering_recipient == recipient


def test_verification_heals_at_two_and_stamps_clear_time():
    makerspace = Makerspace.objects.create(
        name="Verify", slug="custody-verify", superadmin_access_enabled=False
    )
    _recipient(makerspace, 30)
    challenged = _recipient(makerspace, 31, verified=False)
    challenged.challenge_nonce_digest = hashlib.sha256(NONCE).hexdigest()
    challenged.challenge_issued_at = timezone.now()
    challenged.save(
        update_fields=("challenge_nonce_digest", "challenge_issued_at")
    )
    _degraded_state(makerspace)

    with CaptureQueriesContext(connection) as queries:
        verify_recipient(
            recipient_id=challenged.pk,
            makerspace_id=makerspace.pk,
            submitted_nonce=encode_unpadded_base64url(NONCE),
        )

    state = MakerspaceArchiveCustodyState.objects.get(makerspace=makerspace)
    _assert_makerspace_lock_precedes_recipient_locks(queries)
    assert state.state == state.State.HEALTHY
    assert state.reason_code == ""
    assert state.cleared_at is not None
    assert state.last_alarm_at is None
    assert state.triggering_recipient is None


def test_reactivation_heals_at_two_and_stamps_clear_time():
    makerspace = Makerspace.objects.create(
        name="Reactivate",
        slug="custody-reactivate",
        superadmin_access_enabled=False,
    )
    _recipient(makerspace, 40)
    revoked = _recipient(makerspace, 41, revoked=True)
    _degraded_state(makerspace)

    with CaptureQueriesContext(connection) as queries:
        reactivate_recipient(recipient=revoked)

    state = MakerspaceArchiveCustodyState.objects.get(makerspace=makerspace)
    _assert_makerspace_lock_precedes_recipient_locks(queries)
    assert state.state == state.State.HEALTHY
    assert state.cleared_at is not None
    assert state.last_alarm_at is None


def test_alarm_episode_increments_across_separate_degrade_heal_cycles():
    makerspace = Makerspace.objects.create(
        name="Episodes", slug="custody-episodes", superadmin_access_enabled=False
    )
    first = _recipient(makerspace, 50)
    _recipient(makerspace, 51)
    spare = _recipient(makerspace, 52, revoked=True)

    compromise_recipient(recipient=first)
    first_episode = MakerspaceArchiveCustodyState.objects.get(
        makerspace=makerspace
    ).alarm_episode
    reactivate_recipient(recipient=spare)
    compromise_recipient(recipient=spare)

    state = MakerspaceArchiveCustodyState.objects.get(makerspace=makerspace)
    assert first_episode == 1
    assert state.state == state.State.DEGRADED_ONE_RECIPIENT
    assert state.alarm_episode == 2


def test_custody_write_rolls_back_with_recipient_mutation():
    makerspace = Makerspace.objects.create(name="Rollback", slug="custody-rollback")
    recipient = _recipient(makerspace, 60)

    with pytest.raises(RuntimeError), transaction.atomic():
        compromise_recipient(recipient=recipient)
        raise RuntimeError("force outer rollback")

    recipient.refresh_from_db()
    assert recipient.compromised_at is None
    assert not MakerspaceArchiveCustodyState.objects.filter(
        makerspace=makerspace
    ).exists()


def test_count_changing_paths_never_flip_switch_or_add_platform_recipient(settings):
    settings.BACKUP_AGE_RECIPIENT = "age1platform-fallback"
    makerspace = Makerspace.objects.create(
        name="No fallback",
        slug="custody-no-fallback",
        superadmin_access_enabled=False,
    )
    first = _recipient(makerspace, 70)
    second = _recipient(makerspace, 71)
    third = _recipient(makerspace, 72)
    challenged = _recipient(makerspace, 73, verified=False)
    challenged.challenge_nonce_digest = hashlib.sha256(NONCE).hexdigest()
    challenged.challenge_issued_at = timezone.now()
    challenged.save(
        update_fields=("challenge_nonce_digest", "challenge_issued_at")
    )
    expected_ids = {first.pk, second.pk, third.pk, challenged.pk}

    revoke_recipient(recipient=third)
    reactivate_recipient(recipient=third)
    compromise_recipient(recipient=third)
    verify_recipient(
        recipient_id=challenged.pk,
        makerspace_id=makerspace.pk,
        submitted_nonce=encode_unpadded_base64url(NONCE),
    )

    makerspace.refresh_from_db()
    assert makerspace.superadmin_access_enabled is False
    assert set(makerspace.archive_recipients.values_list("pk", flat=True)) == (
        expected_ids
    )
    assert not makerspace.archive_recipients.filter(
        public_recipient=settings.BACKUP_AGE_RECIPIENT
    ).exists()
