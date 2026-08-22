"""Mixed row-predicate handling for target-seeded and tenant MachineTypes."""

import hashlib
import json

from django.db import connections

from .tenant_dump_errors import TenantDumpVerificationError

FINGERPRINT_FIELDS = (
    "name",
    "icon",
    "is_builtin",
    "managing_action",
    "capability_config",
)


def builtin_fingerprint(row):
    payload = {name: row[name] for name in FINGERPRINT_FIELDS}
    if isinstance(payload["capability_config"], str):
        try:
            payload["capability_config"] = json.loads(payload["capability_config"])
        except json.JSONDecodeError as exc:
            raise TenantDumpVerificationError(
                "Target MachineType has invalid capability_config JSON."
            ) from exc
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def resolve_machine_types(using, source_rows, model):
    """Map identical global built-ins and leave custom rows for raw insertion."""
    connection = connections[using]
    quote = connection.ops.quote_name
    columns = (model._meta.pk.column, "slug", *FINGERPRINT_FIELDS)
    sql_columns = ", ".join(quote(name) for name in columns)
    table = quote(model._meta.db_table)
    resolved = {}
    travelling = []
    with connection.cursor() as cursor:
        for row in source_rows:
            if row.get("makerspace_id") is not None:
                travelling.append(row)
                continue
            cursor.execute(
                f"SELECT {sql_columns} FROM {table} "
                f"WHERE {quote('makerspace_id')} IS NULL AND {quote('slug')} = %s",
                [row["slug"]],
            )
            target = cursor.fetchone()
            if target is None:
                raise TenantDumpVerificationError(
                    f"Target-compatible migrations did not seed MachineType {row['slug']!r}."
                )
            target_row = dict(zip(columns, target, strict=True))
            if builtin_fingerprint(target_row) != builtin_fingerprint(row):
                raise TenantDumpVerificationError(
                    f"Seeded MachineType definition differs for slug {row['slug']!r}."
                )
            resolved[(model._meta.label, row[model._meta.pk.attname])] = target_row[
                model._meta.pk.column
            ]
    return resolved, tuple(travelling)
