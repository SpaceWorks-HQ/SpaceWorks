"""Final database cleanup that is safe only after E8 verification."""

from django.db import connections


def drop_staging_schema(schema, *, using="default"):
    quote = connections[using].ops.quote_name
    with connections[using].cursor() as cursor:
        cursor.execute(f"DROP SCHEMA IF EXISTS {quote(schema)} CASCADE")


def staging_schema_exists(schema, *, using="default"):
    with connections[using].cursor() as cursor:
        cursor.execute(
            "SELECT 1 FROM pg_catalog.pg_namespace WHERE nspname = %s", [schema]
        )
        return cursor.fetchone() is not None


def clear_verified_reservations(operation_id, component_ids, *, using="default"):
    """Clear only restored-component entries; shared table guards stay if needed."""
    from apps.backup.models import B1ReservationEntry

    entries = list(B1ReservationEntry.objects.using(using).filter(
        operation_id=operation_id, component_id__in=component_ids
    ))
    targets = {
        (
            entry.safe_payload.get("schema")
            or entry.safe_payload.get("enforcement", {}).get("schema")
            or "public",
            entry.safe_payload.get("table")
            or entry.safe_payload.get("enforcement", {}).get("table"),
        )
        for entry in entries
    }
    B1ReservationEntry.objects.using(using).filter(
        operation_id=operation_id, component_id__in=component_ids
    ).delete()
    connection = connections[using]
    quote = connection.ops.quote_name
    with connection.cursor() as cursor:
        for schema, table in sorted(targets):
            if not table or _target_has_active_reservations(cursor, schema, table):
                continue
            cursor.execute(
                f"DROP TRIGGER IF EXISTS backup_b1_reservation_guard "
                f"ON {quote(schema)}.{quote(table)}"
            )


def _target_has_active_reservations(cursor, schema, table):
    cursor.execute(
        "SELECT 1 FROM public.backup_b1reservationentry entry "
        "JOIN public.backup_b1restorecomponentstate component "
        "ON component.operation_id = entry.operation_id "
        "AND component.component_id = entry.component_id "
        "WHERE component.state <> 'restored' AND entry.installed_at IS NOT NULL "
        "AND COALESCE(entry.safe_payload->>'schema', "
        "entry.safe_payload->'enforcement'->>'schema', 'public') = %s "
        "AND COALESCE(entry.safe_payload->>'table', "
        "entry.safe_payload->'enforcement'->>'table') = %s LIMIT 1",
        [schema, table],
    )
    return cursor.fetchone() is not None
