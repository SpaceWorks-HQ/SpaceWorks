"""Database-aware enabled-mode preflight, shared by HTTP and worker boot."""

from django.conf import settings

from apps.encryption.blind_index import active_generation
from apps.encryption.crypto import PiiUnavailable, is_envelope
from apps.encryption.models import MakerspaceEncryptionKey, PiiBlindIndex
from apps.encryption.registry import all_fields, makerspace_id_for
from apps.encryption.services import unwrap_dek


def assert_ready(*, strict=False):
    if not settings.PII_ENCRYPTION_ENABLED:
        return
    generation = active_generation()
    if PiiBlindIndex.objects.exclude(search_generation=generation).exists():
        raise PiiUnavailable()
    from apps.events.models import EventRegistration
    if EventRegistration.objects.exclude(email_hash_generation__isnull=True).exclude(email_hash_generation=generation).exists():
        raise PiiUnavailable()
    # Existing envelopes imply an owning tenant must have precisely one live DEK,
    # and every retained version needs an authenticated broker preflight.
    owners = set()
    for field in all_fields():
        model = __import__("django.apps", fromlist=["apps"]).apps.get_model(field.model_label)
        for row in model.objects.only("pk", field.field_name).iterator(chunk_size=200):
            raw = row.__dict__.get(field.field_name)
            if is_envelope(raw):
                owners.add(makerspace_id_for(row, field))
    for makerspace_id in owners:
        keys = list(MakerspaceEncryptionKey.objects.filter(makerspace_id=makerspace_id))
        if sum(key.status == key.Status.ACTIVE for key in keys) != 1 or not keys:
            raise PiiUnavailable()
        for key in keys:
            unwrap_dek(key)
    if strict:
        # Strict coverage is checked at source granularity by the reindex command;
        # this catches every present row that lacks an active provenance record.
        for field in all_fields():
            if field.index_kind not in {"bloom", "bloom_exact"}:
                continue
            model = __import__("django.apps", fromlist=["apps"]).apps.get_model(field.model_label)
            for row in model.objects.only("pk", field.field_name).iterator(chunk_size=200):
                raw = row.__dict__.get(field.field_name)
                if raw and not PiiBlindIndex.objects.filter(model_label=field.model_label, object_id=row.pk, field_name=field.field_name, search_generation=generation).exists():
                    raise PiiUnavailable()
