import pytest
from django.utils import timezone

from apps.encryption.brokers.base import WrappedDek
from apps.encryption.models import (
    MakerspaceEncryptionKey,
    PiiBlindIndex,
    SearchKeyGeneration,
)
from apps.events.models import Event, EventRegistration
from apps.tenant_migration.import_keys import install_streamed_deks
from apps.tenant_migration.insertion_errors import ArchiveFormatError
from apps.tenant_migration.tenant_dump_errors import TenantDumpTargetError
from apps.tenant_migration.tenant_dump_target_deks import install_target_deks
from tests.tenant_migration.tenant_dump_d5_helpers import (
    envelope_manifest,
    importing_space,
    safe_target,
    target_identity,
)


pytestmark = pytest.mark.django_db


@pytest.mark.parametrize(
    "forbidden",
    (
        "broker_key_row",
        "blind_index",
        "search_generation",
        "event_blind_index",
        "event_search_generation",
    ),
)
def test_source_cryptographic_state_refuses_before_helper_or_install(
    forbidden, tmp_path, monkeypatch
):
    space = importing_space(f"d5-source-crypto-{forbidden}")
    generation = None
    if forbidden == "broker_key_row":
        MakerspaceEncryptionKey.objects.create(
            makerspace=space,
            version=1,
            wrapped_dek=b"source-broker-row",
            broker_backend="local",
            broker_key_id="source-broker",
        )
    elif forbidden in {"blind_index", "search_generation", "event_search_generation"}:
        generation = SearchKeyGeneration.objects.create(
            generation=1,
            key_fingerprint=b"s" * 32,
            status=SearchKeyGeneration.Status.ACTIVE,
        )
    if forbidden == "blind_index":
        PiiBlindIndex.objects.create(
            makerspace=space,
            model_label="hardware_requests.HardwareRequest",
            object_id=71,
            field_name="requester_name",
            search_generation=generation,
            bloom_bits=b"\0" * 256,
        )
    elif forbidden in {"event_blind_index", "event_search_generation"}:
        now = timezone.now()
        event = Event.objects.create(
            makerspace=space,
            title="Imported event",
            starts_at=now,
            ends_at=now,
        )
        registration = EventRegistration.objects.create(
            event=event,
            name="",
            email="",
            phone="",
        )
        updates = {"email_exact_hash": b"x" * 32}
        if forbidden == "event_search_generation":
            updates = {"email_hash_generation": generation}
        EventRegistration.objects.filter(pk=registration.pk).update(**updates)

    helper_called = False

    def unexpected(_request):
        nonlocal helper_called
        helper_called = True

    monkeypatch.setattr(
        "apps.tenant_migration.tenant_dump_target_deks._run_helper", unexpected
    )
    manifest, envelope = envelope_manifest(tmp_path, space.pk)
    with pytest.raises(TenantDumpTargetError) as caught:
        install_target_deks(
            manifest,
            envelope,
            (target_identity(tmp_path / "identity", 11),),
            safety=safe_target(),
        )

    assert caught.value.code == "source_crypto_state_present"
    assert helper_called is False


class _TargetBroker:
    backend = "local"

    def __init__(self):
        self.calls = []

    def wrap_dek(self, dek, makerspace_id, version):
        self.calls.append((dek, makerspace_id, version))
        return WrappedDek(
            dek=dek,
            wrapped_dek=f"target-wrapped-{makerspace_id}-{version}".encode(),
            broker_key_id="target-broker-key",
        )


def test_installer_preserves_source_owner_and_versions_under_target_broker(monkeypatch):
    space = importing_space("d5-target-wrap")
    broker = _TargetBroker()
    monkeypatch.setattr(
        "apps.encryption.services.configured_broker", lambda: broker
    )
    records = (
        {"version": 3, "status": "rotated", "dek": b"r" * 32},
        {"version": 7, "status": "active", "dek": b"a" * 32},
    )

    versions = install_streamed_deks(
        space,
        iter(records),
        preserved_makerspace_id=space.pk,
    )

    rows = tuple(
        MakerspaceEncryptionKey.objects.filter(makerspace=space).order_by("version")
    )
    assert versions == (3, 7)
    assert [(row.makerspace_id, row.version, row.status) for row in rows] == [
        (space.pk, 3, "rotated"),
        (space.pk, 7, "active"),
    ]
    assert sum(row.status == "active" for row in rows) == 1
    assert all(row.broker_backend == "local" for row in rows)
    assert all(row.broker_key_id == "target-broker-key" for row in rows)
    assert broker.calls == [
        (b"r" * 32, space.pk, 3),
        (b"a" * 32, space.pk, 7),
    ]
    assert all(
        bytes(row.wrapped_dek) not in {b"r" * 32, b"a" * 32} for row in rows
    )


def test_installer_refuses_source_makerspace_id_remap_before_broker_wrap(monkeypatch):
    space = importing_space("d5-target-owner-remap")
    broker_called = False

    def unexpected():
        nonlocal broker_called
        broker_called = True

    monkeypatch.setattr("apps.encryption.services.configured_broker", unexpected)
    with pytest.raises(ArchiveFormatError, match="preserve"):
        install_streamed_deks(
            space,
            iter(({"version": 1, "status": "active", "dek": b"d" * 32},)),
            preserved_makerspace_id=space.pk + 1,
        )

    assert broker_called is False
    assert not MakerspaceEncryptionKey.objects.filter(makerspace=space).exists()
