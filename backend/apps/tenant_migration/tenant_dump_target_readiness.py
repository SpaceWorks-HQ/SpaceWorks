"""Target-owned search derivation and encryption readiness for Lane D."""

from dataclasses import dataclass

from django.apps import apps
from django.db import transaction
from django.utils import timezone

from apps.audit import services as audit
from apps.encryption import services
from apps.encryption.blind_index import (
    event_email_hash,
    search_key_fingerprint,
)
from apps.encryption.crypto import decrypt_with_key_loader, parse_envelope
from apps.encryption.models import PiiBlindIndex, SearchKeyGeneration
from apps.encryption.readiness import assert_ready
from apps.encryption.registry import all_fields
from apps.events.models import EventRegistration
from apps.makerspaces.models import Makerspace

from .blind_indexes import rebuild_blind_indexes, verify_event_hashes
from .target_state import IMPORTING
from .tenant_dump_errors import TenantDumpTargetError


@dataclass(frozen=True)
class TargetEncryptionReadiness:
    search_generation: int
    blind_indexes_created: int
    event_hashes_created: int
    authenticated_samples: int


@transaction.atomic
def create_target_search_generation(makerspace_id, *, actor=None):
    makerspace = _importing_target(makerspace_id)
    tuple(SearchKeyGeneration.objects.select_for_update().all())
    if SearchKeyGeneration.objects.exists() or PiiBlindIndex.objects.exists():
        _refuse(
            "Target search derivation requires empty source-derived tables.",
            "search_state_present",
        )
    if EventRegistration.objects.filter(email_exact_hash__isnull=False).exists():
        _refuse("Source event blind indexes survived the restore.", "search_state_present")
    if EventRegistration.objects.filter(email_hash_generation__isnull=False).exists():
        _refuse("Source event search generations survived the restore.", "search_state_present")
    generation = SearchKeyGeneration.objects.create(
        generation=1,
        key_fingerprint=search_key_fingerprint(),
        status=SearchKeyGeneration.Status.ACTIVE,
        activated_at=timezone.now(),
    )
    audit.record(
        actor,
        "tenant_migration.target_search_generation_created",
        makerspace=makerspace,
        target=generation,
        meta={"generation": generation.generation},
    )
    return generation


def rebuild_target_search_indexes(makerspace_id, *, actor=None, batch_size=500):
    makerspace = _importing_target(makerspace_id)
    if PiiBlindIndex.objects.exists():
        _refuse("Target blind indexes must be empty before rebuilding.", "search_state_present")
    blind_count = rebuild_blind_indexes(makerspace, batch_size=batch_size)
    event_count = _rebuild_event_hashes(makerspace, batch_size=batch_size)
    audit.record(
        actor,
        "tenant_migration.target_blind_indexes_rebuilt",
        makerspace=makerspace,
        target=makerspace,
        meta={
            "blind_indexes_created": blind_count,
            "event_hashes_created": event_count,
        },
    )
    return blind_count, event_count


def run_target_encryption_readiness(
    makerspace_id,
    *,
    actor=None,
    blind_indexes_created=0,
    event_hashes_created=0,
):
    """Run strict coverage plus authenticated deterministic samples before activation."""
    makerspace = _importing_target(makerspace_id)
    try:
        assert_ready(strict=True)
        verify_event_hashes(makerspace)
        sample_count = _authenticated_samples(makerspace)
    except Exception as exc:
        raise TenantDumpTargetError(
            "Target encryption readiness failed.",
            code="encryption_readiness_failed",
        ) from exc
    generation = SearchKeyGeneration.objects.get(status=SearchKeyGeneration.Status.ACTIVE)
    audit.record(
        actor,
        "tenant_migration.target_encryption_ready",
        makerspace=makerspace,
        target=makerspace,
        meta={
            "generation": generation.generation,
            "authenticated_samples": sample_count,
        },
    )
    return TargetEncryptionReadiness(
        search_generation=generation.generation,
        blind_indexes_created=blind_indexes_created,
        event_hashes_created=event_hashes_created,
        authenticated_samples=sample_count,
    )


def rebuild_and_verify_target_encryption(makerspace_id, *, actor=None, batch_size=500):
    generation = create_target_search_generation(makerspace_id, actor=actor)
    blind_count, event_count = rebuild_target_search_indexes(
        makerspace_id,
        actor=actor,
        batch_size=batch_size,
    )
    result = run_target_encryption_readiness(
        makerspace_id,
        actor=actor,
        blind_indexes_created=blind_count,
        event_hashes_created=event_count,
    )
    if result.search_generation != generation.generation:
        _refuse("The target search generation changed during rebuild.", "search_generation_changed")
    return result


def _rebuild_event_hashes(makerspace, *, batch_size):
    generation = SearchKeyGeneration.objects.get(status=SearchKeyGeneration.Status.ACTIVE)
    mapped = next(
        field
        for field in all_fields()
        if field.model_label == "events.EventRegistration" and field.field_name == "email"
    )
    rows = EventRegistration.objects.filter(event__makerspace=makerspace).select_related("event")
    pending = []
    count = 0
    for registration in rows.iterator(chunk_size=batch_size):
        envelope = registration.__dict__.get("email")
        if envelope:
            plaintext = _decrypt_mapped(registration, mapped, envelope, makerspace.pk)
            registration.email_exact_hash = event_email_hash(
                plaintext,
                generation=generation.generation,
                makerspace_id=makerspace.pk,
                event_id=registration.event_id,
            )
            registration.email_hash_generation = generation
            count += 1
        else:
            registration.email_exact_hash = None
            registration.email_hash_generation = None
        pending.append(registration)
        if len(pending) == batch_size:
            EventRegistration.objects.bulk_update(
                pending, ("email_exact_hash", "email_hash_generation")
            )
            pending.clear()
    if pending:
        EventRegistration.objects.bulk_update(
            pending, ("email_exact_hash", "email_hash_generation")
        )
    return count


def _authenticated_samples(makerspace):
    samples = 0
    for mapped in all_fields():
        model = apps.get_model(mapped.model_label)
        tenant_lookup = mapped.makerspace_path.replace(".", "__")
        field = model._meta.get_field(mapped.field_name)
        instance = (
            model.objects.filter(**{tenant_lookup: makerspace.pk})
            .exclude(**{f"{mapped.field_name}__isnull": True})
            .exclude(**{mapped.field_name: ""})
            .only(model._meta.pk.name, mapped.field_name)
            .order_by(model._meta.pk.name)
            .first()
        )
        if instance is None:
            continue
        envelope = instance.__dict__.get(field.attname)
        parse_envelope(envelope)
        _decrypt_mapped(instance, mapped, envelope, makerspace.pk)
        samples += 1
    return samples


def _decrypt_mapped(instance, mapped, envelope, makerspace_id):
    plaintext = decrypt_with_key_loader(
        envelope,
        makerspace_id=makerspace_id,
        table=instance._meta.db_table,
        pk=instance.pk,
        field=mapped.field_name,
        load_dek=lambda version: services.get_dek(makerspace_id, version),
    )
    return plaintext.decode("utf-8") if isinstance(plaintext, bytes) else plaintext


def _importing_target(makerspace_id):
    try:
        return Makerspace.objects.get(pk=makerspace_id, lifecycle_state=IMPORTING)
    except Makerspace.DoesNotExist:
        _refuse("Encryption reconstruction requires the importing target.", "unsafe_target")


def _refuse(message, code):
    raise TenantDumpTargetError(message, code=code)
