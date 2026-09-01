"""Container-side live identity query and consume-only launch exchange."""

import psycopg2

from .database_identity import DatabaseIdentityError, query_live_database_identity
from .host_capability_socket import request_signed_launch_grant
from .host_capability_types import CapabilityError, ConsumeRequest
from .host_marker import MarkerError


def consume_entrypoint_capability(marker, database_url):
    try:
        bound_database = marker.require_bound_database()
    except MarkerError as exc:
        raise CapabilityError("Launch capability requires a bound host marker.") from exc
    if marker.operation is None or bound_database.server_identity is None:
        raise CapabilityError("Host marker lacks H1b capability facts.")
    try:
        with psycopg2.connect(database_url, connect_timeout=5) as database:
            live = query_live_database_identity(database)
    except DatabaseIdentityError:
        raise
    except Exception as exc:
        raise DatabaseIdentityError(
            "Live database identity could not be queried."
        ) from exc
    operation = marker.operation
    if (live.endpoint.database, live.oid) != (
        bound_database.name,
        bound_database.oid,
    ):
        raise CapabilityError("Live sibling database name or OID disagrees with the marker.")
    if live.server_identity() != bound_database.server_identity:
        raise CapabilityError("Live server identity disagrees with the marker.")
    if (live.run_id, live.artifact_sha256, live.capture_id) != (
        operation.restore_id,
        operation.artifact_sha256,
        operation.capture_id,
    ):
        raise CapabilityError("Live database lineage disagrees with the marker.")
    request = ConsumeRequest(
        role="backend",
        restore_id=live.run_id,
        sibling_database_name=live.endpoint.database,
        sibling_database_oid=live.oid,
        server_identity=live.server_identity(),
        artifact_sha256=live.artifact_sha256,
        capture_id=live.capture_id,
    )
    return request_signed_launch_grant(request)
