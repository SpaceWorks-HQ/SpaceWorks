from cryptography.fernet import Fernet
import pytest
from django.test import override_settings
from django.utils import timezone

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.encryption.blind_index import (
    event_email_hash,
    exact_hash,
    search_key_fingerprint,
)
from apps.encryption.brokers.local import LocalMasterKeyBroker
from apps.encryption.crypto import encrypt
from apps.encryption.models import (
    MakerspaceEncryptionKey,
    PiiBlindIndex,
    SearchKeyGeneration,
)
from apps.events.models import Event, EventRegistration
from apps.hardware_requests.models import HardwareRequest
from apps.tenant_migration.tenant_dump_errors import TenantDumpTargetError
from apps.tenant_migration.tenant_dump_target_readiness import (
    rebuild_and_verify_target_encryption,
    run_target_encryption_readiness,
)
from tests.tenant_migration.tenant_dump_d5_helpers import importing_space


pytestmark = pytest.mark.django_db(transaction=True)
TARGET_DEK = b"t" * 32


def _restored_encrypted_request(space, *, master_key):
    user = User.objects.create_user(username=f"{space.slug}-requester")
    with override_settings(PII_ENCRYPTION_ENABLED=False):
        request = HardwareRequest.objects.create(
            makerspace=space,
            requester=user,
            requester_username="",
            requester_name="",
            requester_contact_email="",
            requester_contact_phone="",
            requested_for="readiness",
        )
        name_envelope = encrypt(
            b"Target Search Name",
            TARGET_DEK,
            key_version=7,
            makerspace_id=space.pk,
            table=HardwareRequest._meta.db_table,
            pk=request.pk,
            field="requester_name",
        )
        email_envelope = encrypt(
            b"target-search@example.test",
            TARGET_DEK,
            key_version=7,
            makerspace_id=space.pk,
            table=HardwareRequest._meta.db_table,
            pk=request.pk,
            field="requester_contact_email",
        )
        HardwareRequest.objects.filter(pk=request.pk).update(
            requester_name=name_envelope,
            requester_contact_email=email_envelope,
        )
        event = Event.objects.create(
            makerspace=space,
            title="Target restored event",
            starts_at=timezone.now(),
            ends_at=timezone.now(),
        )
        registration = EventRegistration.objects.create(
            event=event,
            name="",
            email="",
            phone="",
        )
        event_email_envelope = encrypt(
            b"event-target@example.test",
            TARGET_DEK,
            key_version=7,
            makerspace_id=space.pk,
            table=EventRegistration._meta.db_table,
            pk=registration.pk,
            field="email",
        )
        EventRegistration.objects.filter(pk=registration.pk).update(
            email=event_email_envelope,
            email_exact_hash=None,
            email_hash_generation=None,
        )
    wrapped = LocalMasterKeyBroker(master_key=master_key).wrap_dek(
        TARGET_DEK, space.pk, 7
    )
    MakerspaceEncryptionKey.objects.create(
        makerspace=space,
        version=7,
        wrapped_dek=wrapped.wrapped_dek,
        broker_backend="local",
        broker_key_id=wrapped.broker_key_id,
        status=MakerspaceEncryptionKey.Status.ACTIVE,
    )
    return request, registration


def test_target_search_generation_and_blind_indexes_use_target_search_key():
    space = importing_space("d5-target-search")
    target_master = Fernet.generate_key().decode("ascii")
    target_search = Fernet.generate_key().decode("ascii")
    source_search = Fernet.generate_key().decode("ascii")
    request, registration = _restored_encrypted_request(
        space, master_key=target_master
    )
    with override_settings(PII_SEARCH_HASH_KEY=source_search):
        source_generation_fingerprint = search_key_fingerprint()

    with override_settings(
        PII_ENCRYPTION_ENABLED=True,
        PII_ENCRYPTION_DUAL_READ=False,
        PII_KEY_BROKER="local",
        PII_MASTER_KEY=target_master,
        PII_MASTER_KEY_PREVIOUS="",
        PII_SEARCH_HASH_KEY=target_search,
    ):
        expected_generation_fingerprint = search_key_fingerprint()
        readiness = rebuild_and_verify_target_encryption(space.pk)
        generation = SearchKeyGeneration.objects.get()
        email_index = PiiBlindIndex.objects.get(
            makerspace=space,
            model_label="hardware_requests.HardwareRequest",
            object_id=request.pk,
            field_name="requester_contact_email",
        )
        expected_email_hash = exact_hash(
            "target-search@example.test",
            generation=1,
            makerspace_id=space.pk,
            model_label="hardware_requests.HardwareRequest",
            field_name="requester_contact_email",
        )
        expected_event_hash = event_email_hash(
            "event-target@example.test",
            generation=1,
            makerspace_id=space.pk,
            event_id=registration.event_id,
        )
        registration.refresh_from_db()

    assert generation.generation == 1
    assert bytes(generation.key_fingerprint) == expected_generation_fingerprint
    assert bytes(generation.key_fingerprint) != source_generation_fingerprint
    assert bytes(email_index.exact_hash) == expected_email_hash
    assert bytes(registration.email_exact_hash) == expected_event_hash
    assert registration.email_hash_generation_id == 1
    assert readiness.blind_indexes_created == 2
    assert readiness.event_hashes_created == 1
    assert readiness.authenticated_samples == 3
    assert AuditLog.objects.filter(
        makerspace=space,
        action="tenant_migration.target_search_generation_created",
    ).exists()
    assert AuditLog.objects.filter(
        makerspace=space,
        action="tenant_migration.target_encryption_ready",
    ).exists()


def test_strict_readiness_runs_before_authenticated_sample_decrypts(monkeypatch):
    space = importing_space("d5-readiness-order")
    SearchKeyGeneration.objects.create(
        generation=1,
        key_fingerprint=b"f" * 32,
        status=SearchKeyGeneration.Status.ACTIVE,
    )
    calls = []
    monkeypatch.setattr(
        "apps.tenant_migration.tenant_dump_target_readiness.assert_ready",
        lambda *, strict: calls.append(("strict", strict)),
    )
    monkeypatch.setattr(
        "apps.tenant_migration.tenant_dump_target_readiness.verify_event_hashes",
        lambda makerspace: calls.append(("event_hashes", makerspace.pk)),
    )
    monkeypatch.setattr(
        "apps.tenant_migration.tenant_dump_target_readiness._authenticated_samples",
        lambda makerspace: calls.append(("samples", makerspace.pk)) or 4,
    )

    readiness = run_target_encryption_readiness(space.pk)

    assert calls == [
        ("strict", True),
        ("event_hashes", space.pk),
        ("samples", space.pk),
    ]
    assert readiness.authenticated_samples == 4


@pytest.mark.parametrize("failure", ("strict", "samples"))
def test_readiness_failure_is_fail_closed_and_emits_no_ready_audit(
    failure, monkeypatch
):
    space = importing_space(f"d5-readiness-failure-{failure}")
    SearchKeyGeneration.objects.create(
        generation=1,
        key_fingerprint=b"f" * 32,
        status=SearchKeyGeneration.Status.ACTIVE,
    )
    if failure == "strict":
        monkeypatch.setattr(
            "apps.tenant_migration.tenant_dump_target_readiness.assert_ready",
            lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("not ready")),
        )
    else:
        monkeypatch.setattr(
            "apps.tenant_migration.tenant_dump_target_readiness.assert_ready",
            lambda **_kwargs: None,
        )
        monkeypatch.setattr(
            "apps.tenant_migration.tenant_dump_target_readiness.verify_event_hashes",
            lambda _space: None,
        )
        monkeypatch.setattr(
            "apps.tenant_migration.tenant_dump_target_readiness._authenticated_samples",
            lambda _space: (_ for _ in ()).throw(RuntimeError("decrypt failed")),
        )

    with pytest.raises(TenantDumpTargetError) as caught:
        run_target_encryption_readiness(space.pk)

    space.refresh_from_db()
    assert caught.value.code == "encryption_readiness_failed"
    assert space.lifecycle_state == space.LifecycleState.IMPORTING
    assert not AuditLog.objects.filter(
        makerspace=space,
        action="tenant_migration.target_encryption_ready",
    ).exists()
