"""Catalog, raw digest and identity checks shared by scratch and restored dump."""

from django.apps import apps
from django.db import connections

from apps.backup.raw_projection import no_decrypt_guard
from apps.encryption.registry import fields_for

from .tenant_dump_catalog import validate_catalog, validate_unowned_tables
from .tenant_dump_errors import TenantDumpVerificationError
from .tenant_dump_raw import (
    mapped_raw_digest,
    projected_raw_digest,
    validate_raw_column_allowlists,
)
from .tenant_dump_sql import (
    verify_foreign_key_closure,
    verify_open_tenant_fence,
    verify_source_disposition_tables_empty,
    verify_tables_empty,
)
from .tenant_dump_sequences import read_sequence_state


def mapped_rows(using, identities):
    """Read only reviewed mapped columns and their PKs from a projected database."""
    result = {}
    connection = connections[using]
    quote = connection.ops.quote_name
    with no_decrypt_guard(), connection.cursor() as cursor:
        for label, pks in sorted(identities.items()):
            model = apps.get_model(label)
            mapped = fields_for(model)
            if not mapped or not pks:
                continue
            selected = [model._meta.pk.attname] + [item.field_name for item in mapped]
            fields = [model._meta.get_field(name) for name in selected]
            columns = ", ".join(quote(field.column) for field in fields)
            placeholders = ", ".join(["%s"] * len(pks))
            cursor.execute(
                f"SELECT {columns} FROM {quote(model._meta.db_table)} "
                f"WHERE {quote(model._meta.pk.column)} IN ({placeholders}) "
                f"ORDER BY {quote(model._meta.pk.column)}",
                list(pks),
            )
            result[label] = tuple(
                dict(zip((field.attname for field in fields), row, strict=True))
                for row in cursor.fetchall()
            )
    return result


def projected_rows(using, identities):
    result = {}
    with no_decrypt_guard():
        for label, pks in sorted(identities.items()):
            if not pks:
                continue
            model = apps.get_model(label)
            columns = tuple(field.attname for field in model._meta.concrete_fields)
            result[label] = tuple(
                model._base_manager.using(using)
                .filter(pk__in=pks)
                .order_by(model._meta.pk.name)
                .values(*columns)
            )
    return result


def verify_projection_database(
    using,
    makerspace_id,
    *,
    expected_mapped_digest,
    mapped_identities,
    expected_projected_digest=None,
    projected_identities=None,
    expected_sequence_state=None,
):
    validate_catalog()
    validate_raw_column_allowlists()
    validate_unowned_tables(connections[using].introspection.table_names())
    verify_foreign_key_closure(using)
    verify_open_tenant_fence(using, makerspace_id)
    verify_tables_empty(using, {"spaceworks_cache"})
    verify_source_disposition_tables_empty(using)
    actual = mapped_raw_digest(mapped_rows(using, mapped_identities))
    if actual != expected_mapped_digest:
        raise TenantDumpVerificationError(
            "Mapped raw values differ between the immutable image and projection."
        )
    if expected_projected_digest is not None:
        rows = projected_rows(using, projected_identities or {})
        if sum(map(len, rows.values())) != sum(
            len(values) for values in (projected_identities or {}).values()
        ):
            raise TenantDumpVerificationError(
                "The scratch projection is missing an expected row identity."
            )
        if projected_raw_digest(rows) != expected_projected_digest:
            raise TenantDumpVerificationError(
                "A sanitized row differs from its reviewed scratch projection."
            )
    if (
        expected_sequence_state is not None
        and read_sequence_state(using) != expected_sequence_state
    ):
        raise TenantDumpVerificationError(
            "Lane D sequence state changed across the custom dump."
        )
    return actual
