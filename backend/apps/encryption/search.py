"""Scoped candidate generation followed by authenticated source verification."""

from django.conf import settings
from django.db import connection
from rest_framework.exceptions import ValidationError

from apps.encryption.blind_index import active_generation, bloom_bits, canonical_email, exact_hash, normalized_name
from apps.encryption.crypto import is_envelope
from apps.encryption.models import PiiBlindIndex
from apps.encryption.registry import fields_for_label

CANDIDATE_LIMIT = 250


def _limit(rows):
    rows = list(rows[: CANDIDATE_LIMIT + 1])
    if len(rows) > CANDIDATE_LIMIT:
        raise ValidationError({"search": "Refine search."})
    return rows


def indexed_candidates(*, makerspace_id, model_label, field_name, term, exact=False, base_ids=None):
    """Return bounded source IDs. Caller has already performed RBAC scoping."""
    field = next((item for item in fields_for_label(model_label) if item.field_name == field_name), None)
    if field is None or field.index_kind not in {"bloom", "bloom_exact"}:
        return []
    generation = active_generation()
    filters = {"makerspace_id": makerspace_id, "model_label": model_label, "field_name": field_name, "search_generation": generation}
    if base_ids is not None:
        filters["object_id__in"] = base_ids
    if exact:
        filters["exact_hash"] = exact_hash(term, generation=generation.generation, makerspace_id=makerspace_id, model_label=model_label, field_name=field_name)
        return _limit(PiiBlindIndex.objects.filter(**filters).values_list("object_id", flat=True))
    normalized = normalized_name(term)
    if len(normalized) < 3:
        raise ValidationError({"search": "Enter at least three characters."})
    bits = bloom_bits(term, generation=generation.generation, makerspace_id=makerspace_id, model_label=model_label, field_name=field_name)
    qs = PiiBlindIndex.objects.filter(**filters).extra(where=["pii_bloom_contains(bloom_bits, %s)"], params=[bits])
    return _limit(qs.values_list("object_id", flat=True))


def verified_ids(queryset, *, field_name, term, exact=False):
    """Decrypt only candidates and retain semantic matches, never index-only matches."""
    want = canonical_email(term) if exact else normalized_name(term)
    verified = []
    for row in queryset:
        value = getattr(row, field_name)
        if (canonical_email(value) == want) if exact else (want in normalized_name(value)):
            verified.append(row.pk)
    return verified


def legacy_plaintext_candidates(queryset, *, field_name, term, exact=False, batch_size=100):
    """The sole dual-read raw adapter; it rejects envelopes before comparison."""
    if not settings.PII_ENCRYPTION_DUAL_READ:
        return []
    table, column = queryset.model._meta.db_table, queryset.model._meta.get_field(field_name).column
    ids = queryset.order_by("pk").values_list("pk", flat=True)
    found, checkpoint = [], 0
    wanted = canonical_email(term) if exact else normalized_name(term)
    while True:
        batch = list(ids.filter(pk__gt=checkpoint)[:batch_size])
        if not batch:
            return found
        with connection.cursor() as cursor:
            cursor.execute(f'SELECT id, "{column}" FROM "{table}" WHERE id = ANY(%s)', [batch])
            for pk, raw in cursor.fetchall():
                if raw and not is_envelope(raw):
                    current = canonical_email(raw) if exact else normalized_name(raw)
                    if (current == wanted) if exact else (wanted in current):
                        found.append(pk)
        checkpoint = batch[-1]
