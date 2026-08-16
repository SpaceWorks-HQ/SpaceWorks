import secrets
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.encryption.blind_index import active_generation, sync_event_hash
from apps.encryption.crypto import (
    PiiAuthenticationFailed,
    PiiUnavailable,
    decrypt,
    encrypt,
    parse_envelope,
)
from apps.events.models import Event, EventRegistration
from apps.makerspaces.models import Makerspace
from apps.tenant_migration.event_hashes import event_registration_hash_columns
from apps.tenant_migration.pii_reencryption import reencrypt_mapped_value


def test_reencryption_preserves_version_and_rebinds_aad():
    dek = secrets.token_bytes(32)
    source = {
        "makerspace_id": 17,
        "table": "events_eventregistration",
        "pk": 41,
        "field": "email",
    }
    envelope = encrypt(
        b"member@example.test", dek, key_version=7, **source
    )

    rebound = reencrypt_mapped_value(
        envelope,
        source_aad=source,
        target_makerspace_id=23,
        target_table="events_eventregistration",
        target_pk=97,
        target_field="email",
        deks={7: dek},
    )

    assert parse_envelope(rebound)[0] == 7
    assert decrypt(
        rebound,
        dek,
        makerspace_id=23,
        table="events_eventregistration",
        pk=97,
        field="email",
    ) == b"member@example.test"
    with pytest.raises(PiiAuthenticationFailed):
        decrypt(rebound, dek, **source)


@pytest.mark.parametrize(
    "deks,mutate",
    [
        ({8: secrets.token_bytes(32)}, lambda value: value),
        ({7: secrets.token_bytes(32)}, lambda value: value[:-1] + "!"),
    ],
)
def test_reencryption_fails_closed_for_wrong_version_or_corruption(deks, mutate):
    source = {
        "makerspace_id": 17,
        "table": "events_eventregistration",
        "pk": 41,
        "field": "email",
    }
    source_dek = secrets.token_bytes(32)
    envelope = encrypt(b"member@example.test", source_dek, key_version=7, **source)

    with pytest.raises(PiiUnavailable):
        reencrypt_mapped_value(
            mutate(envelope),
            source_aad=source,
            target_makerspace_id=23,
            target_table="events_eventregistration",
            target_pk=97,
            target_field="email",
            deks=deks,
        )


@pytest.mark.django_db
def test_event_hash_columns_match_runtime_target_binding():
    from tests.encryption.conftest import enabled_encryption

    with enabled_encryption():
        space = Makerspace.objects.create(name="Hash Target", slug="hash-target")
        now = timezone.now()
        event = Event.objects.create(
            makerspace=space,
            title="Target event",
            starts_at=now,
            ends_at=now + timedelta(hours=1),
        )
        email = " Member@Example.Test "
        columns = event_registration_hash_columns(
            email,
            target_makerspace_id=space.pk,
            target_event_id=event.pk,
        )

        runtime_registration = EventRegistration(event=event)
        generation = active_generation()
        sync_event_hash(runtime_registration, email, generation)

        assert columns["email_exact_hash"] == runtime_registration.email_exact_hash
        assert (
            columns["email_hash_generation_id"]
            == runtime_registration.email_hash_generation_id
        )
        assert columns["email_hash_generation_id"] == generation.generation
