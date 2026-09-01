"""Create and prove a sibling only inside the H1c marker transition."""

from apps.backup.host_marker import DatabaseIdentity


def prepare_bound_sibling(
    database,
    marker_writer,
    operation,
    *,
    fresh_after_interrupted_restore,
    after_intent=None,
    validate_allocated=None,
):
    marker_writer.write_intent(operation)
    if after_intent is not None:
        after_intent()
    sibling = database.allocate(
        fresh_after_interrupted_restore=fresh_after_interrupted_restore
    )
    if validate_allocated is not None:
        validate_allocated(sibling)
    sibling = database.prove_sibling(sibling)
    marker_writer.bind_database(
        DatabaseIdentity(
            name=sibling.identity.database_name,
            oid=sibling.identity.database_oid,
        ),
        operation,
    )
    return sibling
