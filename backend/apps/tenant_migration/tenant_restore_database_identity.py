"""Live owner/identity revalidation for an already allocated D7 sibling."""

from dataclasses import asdict, replace

from .tenant_restore_types import TenantRestoreRefused


def recover_allocated_sibling(lifecycle, expected, *, identity_reader):
    sibling = lifecycle.allocate(fresh_after_interrupted_restore=False)
    with lifecycle._connect(sibling.database_url) as connection:
        live_identity = identity_reader(connection)
    if asdict(live_identity) != expected.get("identity"):
        raise TenantRestoreRefused("Allocated sibling live identity changed.")
    if sibling.created_by_this_run:
        with lifecycle._connect() as admin, admin.cursor() as cursor:
            cursor.execute(
                "SELECT shobj_description(oid, 'pg_database') FROM pg_database "
                "WHERE datname=%s AND oid=%s",
                [live_identity.database_name, live_identity.database_oid],
            )
            row = cursor.fetchone()
        if row is None or row[0] != expected.get("owner_marker"):
            raise TenantRestoreRefused("Allocated sibling owner marker changed.")
    return replace(
        sibling,
        empty=expected.get("empty") is True,
        owner_marker=expected.get("owner_marker", ""),
    )
