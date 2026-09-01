"""Bounded raw INSERTs for rows that must be final at first persistence."""

from collections.abc import Iterable, Iterator, Mapping
from itertools import islice

from django.db import DatabaseError

from apps.encryption.registry import fields_for

from .insertion_errors import IncompleteImportRow, TenantImportFenceRequired
from .transaction_state import require_import_transaction

DEFAULT_BATCH_SIZE = 500
MAX_QUERY_PARAMETERS = 60_000


def _batches(values: Iterable, size: int) -> Iterator[list]:
    iterator = iter(values)
    while batch := list(islice(iterator, size)):
        yield batch


def _assert_tenant_import_fence(connection):
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT NULLIF(current_setting('app.pii_fence_operation', true), ''),
                   EXISTS (
                       SELECT 1 FROM encryption_piiglobalwritefence
                       WHERE state = 'closed'
                         AND operation_kind = 'tenant_import'
                         AND operation_id::text = current_setting(
                             'app.pii_fence_operation', true
                         )
                       UNION ALL
                       SELECT 1 FROM encryption_piimakerspacewritefence
                       WHERE state = 'closed'
                         AND operation_kind = 'tenant_import'
                         AND operation_id::text = current_setting(
                             'app.pii_fence_operation', true
                         )
                   )
            """
        )
        operation_id, matching_fence = cursor.fetchone()
    if operation_id is None or not matching_fence:
        raise TenantImportFenceRequired(
            "Mapped PII rows require the matching tenant-import fence operation."
        )


class RawImportRepository:
    """Insert complete database rows without model methods, signals, or updates.

    The caller owns one transaction around the entire import. This repository never
    commits or opens chunk transactions: any later error must roll back every inserted
    row, including immutable and PROTECT-linked records.
    """

    def __init__(self, *, using="default"):
        self.using = using

    def insert_rows(
        self,
        model,
        rows: Iterable[Mapping[str, object]],
        *,
        batch_size=DEFAULT_BATCH_SIZE,
    ):
        connection = require_import_transaction(self.using)
        if batch_size < 1:
            raise ValueError("batch_size must be positive.")
        if fields_for(model):
            _assert_tenant_import_fence(connection)

        columns = tuple(field.column for field in model._meta.local_concrete_fields)
        if model._meta.pk.column not in columns:
            raise IncompleteImportRow("Raw import rows must contain an explicit primary key.")
        effective_size = min(batch_size, max(1, MAX_QUERY_PARAMETERS // len(columns)))
        inserted = 0
        for batch in _batches(rows, effective_size):
            self._validate_rows(model, batch, columns)
            self._insert_batch(connection, model, batch, columns)
            inserted += len(batch)
        return inserted

    @staticmethod
    def _validate_rows(model, rows, columns):
        expected = set(columns)
        for row in rows:
            supplied = set(row)
            if supplied != expected:
                missing = sorted(expected - supplied)
                unknown = sorted(supplied - expected)
                raise IncompleteImportRow(
                    f"Incomplete raw row for {model._meta.label}; "
                    f"missing columns={missing}, unknown columns={unknown}."
                )

    @staticmethod
    def _insert_batch(connection, model, rows, columns):
        quote = connection.ops.quote_name
        table_sql = quote(model._meta.db_table)
        columns_sql = ", ".join(quote(column) for column in columns)
        row_sql = "(" + ", ".join(["%s"] * len(columns)) + ")"
        values_sql = ", ".join([row_sql] * len(rows))
        # Prepare every value through its own field rather than binding the Python
        # object directly. The ORM normally does this on the way to the driver, and
        # bypassing `save()` bypasses it too: psycopg2 cannot adapt a `dict`, so a
        # JSONField column fails with "can't adapt type 'dict'". Asking the field also
        # keeps dates, decimals and UUIDs correct without a type table of our own.
        fields_by_column = {
            field.column: field for field in model._meta.local_concrete_fields
        }
        parameters = [
            fields_by_column[column].get_db_prep_save(row[column], connection)
            for row in rows
            for column in columns
        ]
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"INSERT INTO {table_sql} ({columns_sql}) VALUES {values_sql}",
                    parameters,
                )
        except DatabaseError as exc:
            if "pii write fence" in str(exc).lower():
                raise TenantImportFenceRequired(
                    "The mapped row does not match the active tenant-import fence."
                ) from exc
            raise
