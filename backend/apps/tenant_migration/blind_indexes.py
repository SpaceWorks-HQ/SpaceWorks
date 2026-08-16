"""Rebuild target-bound scoped search indexes through the normal DEK path."""

from apps.encryption import services
from apps.encryption.blind_index import (
    active_generation,
    bloom_bits,
    exact_hash,
    event_email_hash,
)
from apps.encryption.crypto import decrypt_with_key_loader
from apps.encryption.models import PiiBlindIndex
from apps.encryption.registry import all_fields
from django.apps import apps

from .insertion_errors import ImportVerificationError


def rebuild_blind_indexes(target, *, batch_size=500):
    generation = active_generation()
    pending = []
    inserted = 0
    for mapped in all_fields():
        if mapped.index_kind not in {"bloom", "bloom_exact"}:
            continue
        model = apps.get_model(mapped.model_label)
        tenant_lookup = mapped.makerspace_path.replace(".", "__")
        field = model._meta.get_field(mapped.field_name)
        rows = model.objects.filter(**{tenant_lookup: target.pk}).only(
            model._meta.pk.name, mapped.field_name
        )
        for instance in rows.iterator(chunk_size=batch_size):
            envelope = instance.__dict__.get(field.attname)
            if not envelope:
                continue
            plaintext = _normal_plaintext(instance, mapped, envelope, target.pk)
            pending.append(
                PiiBlindIndex(
                    makerspace=target,
                    model_label=mapped.model_label,
                    object_id=instance.pk,
                    field_name=mapped.field_name,
                    search_generation=generation,
                    bloom_bits=bloom_bits(
                        plaintext,
                        generation=generation.generation,
                        makerspace_id=target.pk,
                        model_label=mapped.model_label,
                        field_name=mapped.field_name,
                    ),
                    exact_hash=(
                        exact_hash(
                            plaintext,
                            generation=generation.generation,
                            makerspace_id=target.pk,
                            model_label=mapped.model_label,
                            field_name=mapped.field_name,
                        )
                        if mapped.index_kind == "bloom_exact"
                        else None
                    ),
                )
            )
            if len(pending) == batch_size:
                PiiBlindIndex.objects.bulk_create(pending)
                inserted += len(pending)
                pending.clear()
    if pending:
        PiiBlindIndex.objects.bulk_create(pending)
        inserted += len(pending)
    return inserted


def verify_event_hashes(target, *, batch_size=500):
    from apps.events.models import EventRegistration

    generation = active_generation()
    rows = EventRegistration.objects.filter(event__makerspace=target).select_related(
        "event"
    )
    for registration in rows.iterator(chunk_size=batch_size):
        envelope = registration.__dict__.get("email")
        plaintext = _normal_plaintext(
            registration,
            next(
                field
                for field in all_fields()
                if field.model_label == "events.EventRegistration"
                and field.field_name == "email"
            ),
            envelope,
            target.pk,
        ) if envelope else ""
        expected = (
            event_email_hash(
                plaintext,
                generation=generation.generation,
                makerspace_id=target.pk,
                event_id=registration.event_id,
            )
            if plaintext
            else None
        )
        stored = registration.email_exact_hash
        # Postgres hands a BinaryField back as `memoryview`; compare bytes to bytes so
        # a correct hash cannot fail on its container type.
        if isinstance(stored, memoryview):
            stored = stored.tobytes()
        expected_generation = generation.generation if plaintext else None
        if stored != expected or registration.email_hash_generation_id != expected_generation:
            raise ImportVerificationError(
                "An imported event email hash is invalid for registration "
                f"{registration.pk}: stored_hash={stored!r} expected_hash={expected!r} "
                f"stored_generation={registration.email_hash_generation_id!r} "
                f"expected_generation={expected_generation!r}."
            )


def _normal_plaintext(instance, mapped, envelope, makerspace_id):
    plaintext = decrypt_with_key_loader(
        envelope,
        makerspace_id=makerspace_id,
        table=instance._meta.db_table,
        pk=instance.pk,
        field=mapped.field_name,
        load_dek=lambda version: services.get_dek(makerspace_id, version),
    )
    return plaintext.decode("utf-8") if isinstance(plaintext, bytes) else plaintext
