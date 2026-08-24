"""External ledgers and post-restore checks for the readable main."""

from collections import defaultdict
import hashlib
import json

from django.db import connections
from django.db.models import Q

from apps.backup.main_projection_registry import (
    BoundaryDisposition,
    RowDisposition,
    assert_catalog_matches,
    boundary_queryset,
    boundary_rules,
    sovereign_q,
)
from apps.backup.recipient_selection import BackupBuildError
from apps.backup.raw_projection import concrete_record_payload, no_decrypt_guard


def build_expected_ledger(using, rules, makerspace_ids):
    """Capture expected row identities and sequence high-water outside candidates."""
    tables = {}
    dropped_boundaries = defaultdict(list)
    boundaries = boundary_rules(rules)
    boundary_models = {item.source_model for item in boundaries}
    for item in boundaries:
        if item.disposition == BoundaryDisposition.DROP_ROW_TO_SLICE:
            dropped_boundaries[item.source_model].append(item)
    for rule in rules:
        queryset = rule.model._base_manager.using(using).order_by(
            rule.model._meta.pk.name
        )
        if rule.disposition == RowDisposition.OMIT_OPERATIONAL:
            queryset = queryset.none()
        if rule.disposition == RowDisposition.COPY_TO_SLICE:
            queryset = queryset.exclude(sovereign_q(rule.predicate, makerspace_ids))
        if rule.model in dropped_boundaries:
            removed = Q(pk__in=())
            for boundary in dropped_boundaries[rule.model]:
                removed |= Q(
                    pk__in=boundary_queryset(
                        boundary, using, makerspace_ids
                    ).values("pk")
                )
            queryset = queryset.exclude(removed)
        count, identity_digest, row_digest = _queryset_digests(
            queryset, verify_rows=rule.model not in boundary_models
        )
        tables[rule.model._meta.db_table] = {
            "count": count,
            "identity_sha256": identity_digest,
            "raw_rows_sha256": row_digest,
        }
    return {"tables": tables, "sequences": _sequence_ledger(using)}


def verify_readable_main(using, rules, makerspace_ids, expected):
    assert_catalog_matches(using, rules)
    for rule in rules:
        queryset = rule.model._base_manager.using(using).order_by(
            rule.model._meta.pk.name
        )
        if (
            rule.disposition == RowDisposition.OMIT_OPERATIONAL
            and queryset.exists()
        ):
            raise BackupBuildError(
                f"Readable main retains operational rows in {rule.model._meta.db_table}."
            )
        if (
            rule.disposition == RowDisposition.COPY_TO_SLICE
            and queryset.filter(sovereign_q(rule.predicate, makerspace_ids)).exists()
        ):
            raise BackupBuildError(
                f"Readable main retains sovereign rows in {rule.model._meta.db_table}."
            )
        fact = expected["tables"][rule.model._meta.db_table]
        count, identity_digest, row_digest = _queryset_digests(
            queryset, verify_rows=fact["raw_rows_sha256"] is not None
        )
        if (
            count != fact["count"]
            or identity_digest != fact["identity_sha256"]
            or row_digest != fact["raw_rows_sha256"]
        ):
            raise BackupBuildError(
                f"Readable-main row verification failed for {rule.model._meta.db_table}."
            )
    if _sequence_ledger(using) != expected["sequences"]:
        raise BackupBuildError("Readable-main sequence high-water verification failed.")


def _queryset_digests(queryset, *, verify_rows):
    identity_digest = hashlib.sha256()
    row_digest = hashlib.sha256() if verify_rows else None
    count = 0
    fields = tuple(field.attname for field in queryset.model._meta.concrete_fields)
    with no_decrypt_guard():
        for record in queryset.values(*fields).iterator(chunk_size=2000):
            identity_digest.update(str(record[queryset.model._meta.pk.attname]).encode())
            identity_digest.update(b"\0")
            if row_digest is not None:
                row_digest.update(
                    json.dumps(
                        concrete_record_payload(queryset.model, record),
                        sort_keys=True,
                    ).encode("utf-8")
                )
                row_digest.update(b"\0")
            count += 1
    return (
        count,
        identity_digest.hexdigest(),
        row_digest.hexdigest() if row_digest is not None else None,
    )


def _sequence_ledger(using):
    result = {}
    connection = connections[using]
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT n.nspname, c.relname, s.seqstart, s.seqincrement,
                   s.seqmin, s.seqmax, s.seqcache, s.seqcycle
              FROM pg_catalog.pg_sequence s
              JOIN pg_catalog.pg_class c ON c.oid = s.seqrelid
              JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
             WHERE n.nspname = 'public'
             ORDER BY c.relname
            """
        )
        definitions = cursor.fetchall()
        for _schema, name, *definition in definitions:
            quoted = connection.ops.quote_name(name)
            cursor.execute(f"SELECT last_value, is_called FROM {quoted}")
            last_value, is_called = cursor.fetchone()
            result[name] = [*definition, last_value, is_called]
    return result
