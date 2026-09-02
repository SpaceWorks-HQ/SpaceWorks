"""Bulk primary-key reservation backed by a transaction-local PostgreSQL map."""

from collections.abc import Iterable, Iterator
from itertools import islice
from uuid import UUID

from django.db import models

from .insertion_errors import PrimaryKeyMapUnavailable, UnsupportedPrimaryKey
from .transaction_state import require_import_transaction

TABLE_NAME = "tenant_import_pk_map"
DEFAULT_BATCH_SIZE = 1_000

# The only primary-key shapes an import can reserve target values for.
AUTO_PK_FIELD_TYPES = (models.AutoField, models.BigAutoField, models.SmallAutoField)
SUPPORTED_PK_FIELD_TYPES = (*AUTO_PK_FIELD_TYPES, models.UUIDField)

# How many defaults to draw when checking that a UUID primary key can actually mint
# distinct values. Two is enough to catch a missing or constant default.
_UUID_DEFAULT_SAMPLE = 2


def unsupported_primary_key_reason(model, sample=_UUID_DEFAULT_SAMPLE):
    """Why an import cannot reserve target primary keys for ``model``, else ``None``.

    Exported so the projected-catalog guard enforces what reservation actually
    requires rather than a weaker approximation of it. Being a ``UUIDField`` is not
    sufficient: the field also has to supply a default that mints distinct UUIDs, so
    a ``UUIDField(primary_key=True)`` declared without ``default=uuid.uuid4`` is
    still unreservable and must be reported as such.
    """
    pk_field = model._meta.pk
    if isinstance(pk_field, AUTO_PK_FIELD_TYPES):
        return None
    if not isinstance(pk_field, models.UUIDField):
        return f"{model._meta.label} does not use an auto-integer or UUID primary key."
    values = [pk_field.get_default() for _index in range(sample)]
    if any(not isinstance(value, UUID) for value in values) or len(set(values)) != sample:
        return f"{model._meta.label} does not provide unique UUID primary keys."
    return None


def _batches(values: Iterable, size: int) -> Iterator[list]:
    iterator = iter(values)
    while batch := list(islice(iterator, size)):
        yield batch


class TransactionPkMap:
    """Source-to-target identifiers that exist only for the current transaction.

    The PostgreSQL temporary table is dropped on commit. It cannot serve as durable
    provenance: any source identifier needed after import must be persisted on a real
    model while this transaction and its mappings still exist.
    """

    def __init__(self, *, using="default"):
        self.using = using
        self.connection = require_import_transaction(using)
        with self.connection.cursor() as cursor:
            cursor.execute(
                f"""
                CREATE TEMPORARY TABLE IF NOT EXISTS {TABLE_NAME} (
                    model_label text NOT NULL,
                    source_pk text NOT NULL,
                    target_pk text NOT NULL,
                    PRIMARY KEY (model_label, source_pk)
                ) ON COMMIT DROP
                """
            )

    def add_many(
        self,
        model,
        mappings: Iterable[tuple[object, object]],
        *,
        batch_size=DEFAULT_BATCH_SIZE,
    ):
        """Add mappings in bounded, single-statement batches."""
        require_import_transaction(self.using)
        if batch_size < 1:
            raise ValueError("batch_size must be positive.")
        for batch in _batches(mappings, batch_size):
            self._insert_mapping_batch(model, batch)

    def _insert_mapping_batch(self, model, mappings):
        labels = [model._meta.label] * len(mappings)
        sources = [str(source) for source, _target in mappings]
        targets = [str(target) for _source, target in mappings]
        with self.connection.cursor() as cursor:
            cursor.execute(
                f"""
                INSERT INTO {TABLE_NAME} (model_label, source_pk, target_pk)
                SELECT * FROM unnest(%s::text[], %s::text[], %s::text[])
                """,
                [labels, sources, targets],
            )

    def reserve(self, model, source_pks: Iterable, *, batch_size=DEFAULT_BATCH_SIZE):
        """Reserve and store target IDs without materializing all source IDs."""
        if batch_size < 1:
            raise ValueError("batch_size must be positive.")
        for source_batch in _batches(source_pks, batch_size):
            target_batch = self._reserve_target_pks(model, len(source_batch))
            self._insert_mapping_batch(
                model, list(zip(source_batch, target_batch, strict=True))
            )

    def lookup(self, model, source_pk):
        require_import_transaction(self.using)
        with self.connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT target_pk FROM {TABLE_NAME}
                WHERE model_label = %s AND source_pk = %s
                """,
                [model._meta.label, str(source_pk)],
            )
            row = cursor.fetchone()
        if row is None:
            raise PrimaryKeyMapUnavailable(
                f"No primary-key mapping exists for {model._meta.label}."
            )
        return model._meta.pk.to_python(row[0])

    def count(self, model):
        require_import_transaction(self.using)
        with self.connection.cursor() as cursor:
            cursor.execute(
                f"SELECT COUNT(*) FROM {TABLE_NAME} WHERE model_label = %s",
                [model._meta.label],
            )
            return cursor.fetchone()[0]

    def existing_target_count(self, model):
        """Count mappings whose final target row exists in the current transaction."""
        require_import_transaction(self.using)
        quote = self.connection.ops.quote_name
        table = quote(model._meta.db_table)
        pk = quote(model._meta.pk.column)
        cast = model._meta.pk.db_type(self.connection)
        with self.connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT COUNT(*) FROM {TABLE_NAME} map
                JOIN {table} target ON target.{pk} = map.target_pk::{cast}
                WHERE map.model_label = %s
                """,
                [model._meta.label],
            )
            return cursor.fetchone()[0]

    def _reserve_target_pks(self, model, count):
        pk_field = model._meta.pk
        if isinstance(pk_field, AUTO_PK_FIELD_TYPES):
            with self.connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT nextval(pg_get_serial_sequence(%s, %s))
                    FROM generate_series(1, %s)
                    """,
                    [model._meta.db_table, pk_field.column, count],
                )
                return [row[0] for row in cursor.fetchall()]
        if isinstance(pk_field, models.UUIDField):
            return self._unused_uuids(model, count)
        raise UnsupportedPrimaryKey(unsupported_primary_key_reason(model))

    def _unused_uuids(self, model, count):
        pk_field = model._meta.pk
        values = [pk_field.get_default() for _index in range(count)]
        if any(not isinstance(value, UUID) for value in values) or len(set(values)) != count:
            raise UnsupportedPrimaryKey(
                f"{model._meta.label} does not provide unique UUID primary keys."
            )
        quoted_table = self.connection.ops.quote_name(model._meta.db_table)
        quoted_pk = self.connection.ops.quote_name(pk_field.column)
        with self.connection.cursor() as cursor:
            cursor.execute(
                f"SELECT {quoted_pk} FROM {quoted_table} WHERE {quoted_pk} = ANY(%s)",
                [values],
            )
            collisions = cursor.fetchall()
        if collisions:
            # A UUID collision is exceptional rather than silently weakening the map's
            # one-reservation-per-batch database-round-trip contract.
            raise PrimaryKeyMapUnavailable(
                f"A generated UUID for {model._meta.label} is already in use."
            )
        return values
