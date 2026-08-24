"""Authoritative live database identity for host-orchestrated cutovers."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
from pathlib import Path
import re
import uuid


IDENTITY_TABLE = "backup_deploymentdatabaseidentity"
SHA256 = re.compile(r"^[0-9a-f]{64}$")


class DatabaseIdentityError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class DatabaseEndpoint:
    host: str
    port: int
    database: str
    tls_identity: str


@dataclass(frozen=True, slots=True)
class LiveDatabaseIdentity:
    endpoint: DatabaseEndpoint
    oid: int
    database_uuid: str
    system_identifier: str | None
    run_id: str | None
    artifact_sha256: str
    capture_id: str | None

    def server_identity(self):
        return {
            "endpoint": asdict(self.endpoint),
            "database_uuid": self.database_uuid,
            "system_identifier": self.system_identifier,
        }


def _tls_identity(parameters):
    mode = parameters.get("sslmode", "")
    root = parameters.get("sslrootcert", "")
    if mode not in {"verify-ca", "verify-full"} or not root:
        return ""
    try:
        digest = hashlib.sha256(Path(root).read_bytes()).hexdigest()
    except OSError as exc:
        raise DatabaseIdentityError(
            "The configured PostgreSQL TLS trust identity is unreadable."
        ) from exc
    return f"{mode}:sha256:{digest}"


def _system_identifier(cursor, *, autocommit):
    if autocommit:
        try:
            cursor.execute("SELECT system_identifier::text FROM pg_control_system()")
            return cursor.fetchone()[0]
        except Exception:
            return None
    cursor.execute("SAVEPOINT spaceworks_system_identity")
    try:
        cursor.execute("SELECT system_identifier::text FROM pg_control_system()")
        value = cursor.fetchone()[0]
    except Exception:
        cursor.execute("ROLLBACK TO SAVEPOINT spaceworks_system_identity")
        value = None
    finally:
        cursor.execute("RELEASE SAVEPOINT spaceworks_system_identity")
    return value


def query_live_database_identity(connection):
    """Query endpoint + deployment UUID; pg_control is corroboration only."""
    parameters = connection.get_dsn_parameters()
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT current_database(), oid FROM pg_database "
            "WHERE datname = current_database()"
        )
        name, oid = cursor.fetchone()
        cursor.execute("SELECT to_regclass(%s)", [f"public.{IDENTITY_TABLE}"])
        if cursor.fetchone()[0] is None:
            raise DatabaseIdentityError(
                "The deployment database-identity singleton is unavailable."
            )
        cursor.execute(
            f"SELECT database_uuid::text, run_id::text, artifact_sha256, "
            f"capture_id::text FROM {IDENTITY_TABLE} WHERE id = 1"
        )
        row = cursor.fetchone()
        if row is None:
            raise DatabaseIdentityError(
                "The deployment database-identity singleton is missing."
            )
        database_uuid, run_id, artifact_sha256, capture_id = row
        system_identifier = _system_identifier(
            cursor, autocommit=bool(connection.autocommit)
        )
    endpoint = DatabaseEndpoint(
        host=parameters.get("host", ""),
        port=int(parameters.get("port") or 5432),
        database=name,
        tls_identity=_tls_identity(parameters),
    )
    if not endpoint.host or not database_uuid:
        raise DatabaseIdentityError("The authoritative database identity is incomplete.")
    return LiveDatabaseIdentity(
        endpoint=endpoint,
        oid=int(oid),
        database_uuid=database_uuid,
        system_identifier=system_identifier,
        run_id=run_id,
        artifact_sha256=artifact_sha256,
        capture_id=capture_id,
    )


def establish_restored_database_identity(*, run_id, artifact_sha256, capture_id, using="default"):
    """Create a fresh singleton only after restore has omitted the source row."""
    from django.db import transaction

    from .models_host_identity import DeploymentDatabaseIdentity

    if not SHA256.fullmatch(artifact_sha256):
        raise DatabaseIdentityError("Restored database artifact digest is invalid.")
    try:
        run_id = uuid.UUID(str(run_id))
        capture_id = uuid.UUID(str(capture_id))
    except ValueError as exc:
        raise DatabaseIdentityError("Restored database lineage UUID is invalid.") from exc
    with transaction.atomic(using=using):
        if DeploymentDatabaseIdentity.objects.using(using).exists():
            raise DatabaseIdentityError(
                "Restored database already has an identity; pointer comparison is insufficient."
            )
        return DeploymentDatabaseIdentity.objects.using(using).create(
            pk=1,
            database_uuid=uuid.uuid4(),
            run_id=run_id,
            artifact_sha256=artifact_sha256,
            capture_id=capture_id,
        )
