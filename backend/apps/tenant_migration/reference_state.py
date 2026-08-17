"""Transaction-local, bounded access to semantic-reference provenance."""

import json

from .transaction_state import require_import_transaction

TABLE_NAME = "tenant_import_reference_state"


class ReferenceState:
    def __init__(self, archive, *, using="default"):
        self.connection = require_import_transaction(using)
        with self.connection.cursor() as cursor:
            cursor.execute(
                f"""
                CREATE TEMPORARY TABLE {TABLE_NAME} (
                    source_model_label text NOT NULL,
                    source_object_id text NOT NULL,
                    field_name text NOT NULL,
                    kind text NOT NULL,
                    detail jsonb NOT NULL,
                    PRIMARY KEY (source_model_label, source_object_id, field_name)
                ) ON COMMIT DROP
                """
            )
        self._load(archive)

    def _load(self, archive):
        batch = []
        for record in archive.json_lines("migration/reference_provenance.jsonl"):
            batch.append(
                (
                    record["source_model_label"],
                    str(record["source_object_id"]),
                    record["field_name"],
                    record["kind"],
                    json.dumps(record.get("detail", {})),
                )
            )
            if len(batch) == 500:
                self._insert(batch)
                batch.clear()
        if batch:
            self._insert(batch)
        batch = []
        for record in archive.json_lines("migration/external_references.jsonl"):
            batch.append(
                (
                    record["source_model_label"],
                    str(record["source_object_id"]),
                    record["field_name"],
                    "external_reference",
                    json.dumps(record),
                )
            )
            if len(batch) == 500:
                self._insert(batch)
                batch.clear()
        if batch:
            self._insert(batch)

    def _insert(self, batch):
        with self.connection.cursor() as cursor:
            cursor.executemany(
                f"""
                INSERT INTO {TABLE_NAME}
                    (source_model_label, source_object_id, field_name, kind, detail)
                VALUES (%s, %s, %s, %s, %s::jsonb)
                """,
                batch,
            )

    def get(self, model_label, source_object_id, field_name):
        with self.connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT kind, detail FROM {TABLE_NAME}
                WHERE source_model_label=%s AND source_object_id=%s AND field_name=%s
                """,
                [model_label, str(source_object_id), field_name],
            )
            row = cursor.fetchone()
        if row is None:
            return None
        # Django's psycopg2 backend decodes jsonb at the FIELD layer, not the
        # connection layer, so a raw cursor hands back the column as text. Every
        # existing consumer only tested this record for existence, which is why a
        # string detail went unnoticed until a caller first read into it.
        detail = row[1]
        return {
            "kind": row[0],
            "detail": json.loads(detail) if isinstance(detail, str) else detail,
        }

    def external_snapshot(self, model_label, source_object_id, field_name):
        """Return a closure snapshot only when the record declares that shape."""
        record = self.get(model_label, source_object_id, field_name)
        if record is None or record["kind"] != "external_reference":
            return None
        return record["detail"]["snapshot"]

    def count(self):
        with self.connection.cursor() as cursor:
            cursor.execute(f"SELECT COUNT(*) FROM {TABLE_NAME}")
            return cursor.fetchone()[0]
