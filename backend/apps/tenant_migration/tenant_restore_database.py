"""PostgreSQL privilege probes and owner-marked sibling lifecycle for D7."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
import subprocess
from urllib.parse import quote, unquote, urlsplit, urlunsplit

import psycopg2
from psycopg2 import sql

from apps.backup.database_grants import (
    GrantTarget,
    apply_grant_state,
    provision_runtime_role,
)
from apps.backup.host_marker import MarkerState
from apps.backup.postgres_client import client_binary

from .tenant_restore_database_privileges import probe_postgres_privileges
from .tenant_restore_database_identity import recover_allocated_sibling
from .tenant_restore_pgpass import pg_restore_process_inputs
from .tenant_restore_types import (
    PrivilegeFacts,
    ResourceIdentity,
    SiblingPlan,
    SiblingResource,
    TenantRestoreRefused,
)


OWNER_MARKER_KIND = "spaceworks-lane-d-target-v1"


def _database_url(url, name):
    parsed = urlsplit(url)
    return urlunsplit((parsed.scheme, parsed.netloc, "/" + quote(name, safe=""), parsed.query, ""))


def _runtime_credentials(url):
    parsed = urlsplit(url)
    if parsed.scheme not in {"postgres", "postgresql"} or not parsed.username or parsed.password is None:
        raise TenantRestoreRefused("Runtime PostgreSQL URL must contain a role and password.")
    return unquote(parsed.username), unquote(parsed.password)


def _resource_identity(connection):
    parameters = connection.get_dsn_parameters()
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT current_database(), oid FROM pg_database WHERE datname=current_database()"
        )
        name, oid = cursor.fetchone()
    host = parameters.get("host") or ""
    port = parameters.get("port") or "5432"
    return ResourceIdentity(
        endpoint=f"{host}:{port}", database_name=name, database_oid=int(oid)
    )


class PostgresSiblingLifecycle:
    def __init__(
        self, *, maintenance_url, runtime_url, run_id, artifact_sha256,
        planned_name, source_identity, current_identity, supplied_url=None,
        non_routable_guaranteed=False, provider_guarantees_empty=False,
        scratch_identity=None, target_major=16, cleanup_reporter=print,
    ):
        self.maintenance_url = maintenance_url
        self.runtime_url = runtime_url
        self.run_id = str(run_id)
        self.artifact_sha256 = artifact_sha256
        self.planned_name = planned_name
        self.source = source_identity
        self.current = current_identity
        self.supplied_url = supplied_url
        self.non_routable = non_routable_guaranteed
        self.provider_empty = provider_guarantees_empty
        self.scratch = scratch_identity
        self.target_major = target_major
        self.cleanup_reporter = cleanup_reporter
        self.runtime_role, self.runtime_password = _runtime_credentials(runtime_url)
        self._last = None

    def _connect(self, url=None):
        return psycopg2.connect(url or self.maintenance_url)

    def privilege_facts(self):
        try:
            with self._connect(self.supplied_url or self.maintenance_url) as connection:
                return probe_postgres_privileges(connection, runtime_role=self.runtime_role)
        except Exception:
            return PrivilegeFacts(False, False, False, False, False, False)

    def source_identity(self):
        return self.source

    def scratch_identity(self):
        return self.scratch

    def sibling_plan(self):
        identity = None
        if self.supplied_url:
            try:
                with self._connect(self.supplied_url) as connection:
                    identity = _resource_identity(connection)
            except Exception as exc:
                raise TenantRestoreRefused("The supplied sibling identity cannot be probed.") from exc
        return SiblingPlan(
            supplied=bool(self.supplied_url),
            non_routable_guaranteed=self.non_routable,
            provider_guarantees_empty=self.provider_empty,
            planned_name=self.planned_name,
            planned_identity=identity,
        )

    def _marker(self):
        return json.dumps({
            "kind": OWNER_MARKER_KIND,
            "run_id": self.run_id,
            "artifact_sha256": self.artifact_sha256,
        }, sort_keys=True, separators=(",", ":"))

    def allocate(self, *, fresh_after_interrupted_restore):
        if self.supplied_url:
            if fresh_after_interrupted_restore:
                raise TenantRestoreRefused(
                    "Interrupted restore requires a fresh operator-supplied sibling."
                )
            url = self.supplied_url
            created = False
        else:
            if fresh_after_interrupted_restore and self._last is not None:
                self.cleanup(self._last, successful=False)
            with self._connect() as admin:
                admin.autocommit = True
                with admin.cursor() as cursor:
                    cursor.execute(
                        "SELECT oid, shobj_description(oid, 'pg_database') "
                        "FROM pg_database WHERE datname=%s",
                        [self.planned_name],
                    )
                    existing = cursor.fetchone()
                    if existing is None:
                        cursor.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(self.planned_name)))
                    elif existing[1] != self._marker():
                        raise TenantRestoreRefused(
                            "Existing sibling lacks this run's owner marker."
                        )
                    elif fresh_after_interrupted_restore:
                        cursor.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(
                            sql.Identifier(self.planned_name)
                        ))
                        cursor.execute(sql.SQL("CREATE DATABASE {}").format(
                            sql.Identifier(self.planned_name)
                        ))
                    cursor.execute(
                        sql.SQL("COMMENT ON DATABASE {} IS %s").format(sql.Identifier(self.planned_name)),
                        [self._marker()],
                    )
            url = _database_url(self.maintenance_url, self.planned_name)
            created = True
        with self._connect(url) as connection:
            identity = _resource_identity(connection)
        sibling = SiblingResource(
            identity=identity,
            database_url=url,
            empty=False,
            non_routable=self.non_routable,
            created_by_this_run=created,
            owner_marker=self._marker() if created else "",
        )
        self._last = sibling
        return sibling

    def prove_sibling(self, sibling):
        if not sibling.non_routable:
            raise TenantRestoreRefused("Sibling routing isolation is unproved.")
        if sibling.identity.durable_key() in {
            self.source.durable_key(), self.current.durable_key(),
            *( [self.scratch.durable_key()] if self.scratch else [] ),
        }:
            raise TenantRestoreRefused("Source and scratch/sibling identities match.")
        with self._connect(sibling.database_url) as connection:
            connection.autocommit = True
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname=current_database() AND pid<>pg_backend_pid()"
                )
                cursor.fetchall()
                cursor.execute(
                    "SELECT COUNT(*) FROM pg_stat_activity "
                    "WHERE datname=current_database() AND pid<>pg_backend_pid()"
                )
                if cursor.fetchone()[0] != 0:
                    raise TenantRestoreRefused("Sibling sessions cannot be excluded.")
                cursor.execute(
                    "SELECT ("
                    "EXISTS(SELECT 1 FROM pg_class relation JOIN pg_namespace namespace "
                    "ON namespace.oid=relation.relnamespace WHERE namespace.nspname "
                    "NOT IN ('pg_catalog','information_schema') AND namespace.nspname "
                    "NOT LIKE 'pg_toast%') OR "
                    "EXISTS(SELECT 1 FROM pg_proc routine JOIN pg_namespace namespace "
                    "ON namespace.oid=routine.pronamespace WHERE namespace.nspname "
                    "NOT IN ('pg_catalog','information_schema') AND namespace.nspname "
                    "NOT LIKE 'pg_toast%') OR "
                    "EXISTS(SELECT 1 FROM pg_namespace WHERE nspname NOT IN "
                    "('public','pg_catalog','information_schema') AND nspname NOT LIKE "
                    "'pg_toast%') OR EXISTS(SELECT 1 FROM pg_extension WHERE extname "
                    "<> 'plpgsql'))"
                )
                empty = cursor.fetchone()[0] is False
        if not empty:
            raise TenantRestoreRefused("Sibling database is not empty.")
        return replace(sibling, empty=True)

    def recover_sibling(self, expected):
        return recover_allocated_sibling(
            self, expected, identity_reader=_resource_identity
        )

    def restore(self, sibling, dump_path):
        try:
            with pg_restore_process_inputs(sibling.database_url) as environment:
                subprocess.run([
                    client_binary("pg_restore", self.target_major), "--exit-on-error",
                    "--no-owner", "--no-acl", str(Path(dump_path)),
                ], env=environment, check=True, stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE)
        except (OSError, subprocess.CalledProcessError) as exc:
            raise TenantRestoreRefused("pg_restore failed for the empty sibling.") from exc

    def apply_runtime_ownership_and_grants(self, sibling):
        with self._connect(sibling.database_url) as connection:
            connection.autocommit = True
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT EXISTS(SELECT 1 FROM pg_class relation JOIN pg_namespace "
                    "namespace ON namespace.oid=relation.relnamespace JOIN pg_roles owner "
                    "ON owner.oid=relation.relowner WHERE namespace.nspname NOT IN "
                    "('pg_catalog','information_schema') AND namespace.nspname NOT LIKE "
                    "'pg_toast%' AND owner.rolname<>current_user) OR EXISTS(SELECT 1 "
                    "FROM pg_proc routine JOIN pg_namespace namespace ON namespace.oid="
                    "routine.pronamespace JOIN pg_roles owner ON owner.oid=routine.proowner "
                    "WHERE namespace.nspname NOT IN ('pg_catalog','information_schema') "
                    "AND namespace.nspname NOT LIKE 'pg_toast%' AND owner.rolname<>current_user)"
                )
                if cursor.fetchone()[0]:
                    raise TenantRestoreRefused(
                        "Restored object ownership was not re-established."
                    )
                target = GrantTarget(sibling.identity.database_name, self.runtime_role)
                provision_runtime_role(cursor, target, self.runtime_password)
                apply_grant_state(cursor, target, MarkerState.CANDIDATE_PREPARATION)

    def cleanup(self, sibling, *, successful):
        exact = f"{sibling.identity.endpoint}/{sibling.identity.database_name} oid={sibling.identity.database_oid}"
        if not sibling.created_by_this_run:
            result = f"operator cleanup required for verified resource {exact}"
            self.cleanup_reporter(result)
            return result
        with self._connect() as admin:
            admin.autocommit = True
            with admin.cursor() as cursor:
                cursor.execute(
                    "SELECT oid, shobj_description(oid, 'pg_database') FROM pg_database WHERE datname=%s",
                    [sibling.identity.database_name],
                )
                row = cursor.fetchone()
                if row != (sibling.identity.database_oid, sibling.owner_marker):
                    raise TenantRestoreRefused("Owned sibling marker or live identity changed.")
                cursor.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(sibling.identity.database_name)))
        self._last = None
        result = f"dropped verified owned resource {exact}"
        self.cleanup_reporter(result)
        return result

    def database_marker_matches(self, sibling, expected):
        try:
            with self._connect(sibling.database_url) as connection, connection.cursor() as cursor:
                cursor.execute(
                    "SELECT database_uuid::text, run_id::text, artifact_sha256, capture_id::text "
                    "FROM backup_deploymentdatabaseidentity WHERE id=1"
                )
                row = cursor.fetchone()
        except Exception:
            return False
        return row == (
            expected["database_uuid"], expected["run_id"],
            expected["artifact_sha256"], expected["capture_id"],
        )
