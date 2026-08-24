"""Lane E database adapter over D7's proven PostgreSQL sibling lifecycle."""

from dataclasses import replace

from apps.backup.database_grants import (
    GrantTarget,
    apply_grant_state as apply_shared_grant_state,
)
from apps.backup.database_identity import (
    DatabaseIdentityError,
    query_live_database_identity,
)
from apps.backup.host_marker import DatabaseIdentity
from apps.tenant_migration.tenant_restore_database import (
    PostgresSiblingLifecycle,
    _resource_identity,
)
from apps.tenant_migration.tenant_restore_types import ResourceIdentity

from .compound_restore_types import CompoundRestoreRefused


class CompoundPostgresLifecycle(PostgresSiblingLifecycle):
    """Add E9b identity/grant facts without duplicating D7 restore mechanics."""

    def preflight(self):
        privileges = self.privilege_facts()
        plan = self.sibling_plan()
        return {
            "privileges_probed": privileges.probed,
            "can_restore": (
                privileges.can_restore_schema
                and privileges.can_apply_ownership
            ),
            "can_apply_grants": privileges.can_apply_runtime_grants,
            "can_exclude_sessions": privileges.can_exclude_sessions,
            "empty_sibling": (
                not plan.supplied or plan.provider_guarantees_empty
            ),
            "non_routable_sibling": plan.non_routable_guaranteed,
        }

    def recover_sibling(self, expected):
        sibling = self.allocate(fresh_after_interrupted_restore=False)
        identity = expected.get("identity") if isinstance(expected, dict) else None
        if isinstance(identity, list) and len(identity) == 5 and identity[2]:
            sibling = replace(sibling, identity=self.query_identity(sibling))
        if (
            not isinstance(identity, list)
            or len(identity) != 5
            or sibling.identity.durable_key() != tuple(identity)
            or sibling.owner_marker != expected.get("owner_marker", "")
        ):
            raise CompoundRestoreRefused(
                "The compound sibling identity or ownership proof changed."
            )
        return replace(sibling, empty=expected.get("empty") is True)

    def apply_runtime_ownership_and_grants(self, sibling):
        try:
            super().apply_runtime_ownership_and_grants(sibling)
        except Exception:
            raise CompoundRestoreRefused(
                "The candidate role/grant reprovisioning failed."
            ) from None
        return {
            "state": "candidate-preparation",
            "runtime_role": self.runtime_role,
            "writable": False,
        }

    def apply_grant_state(self, sibling, state):
        try:
            with self._connect(sibling.database_url) as connection:
                connection.autocommit = True
                with connection.cursor() as cursor:
                    apply_shared_grant_state(
                        cursor,
                        GrantTarget(
                            sibling.identity.database_name,
                            self.runtime_role,
                        ),
                        state,
                    )
        except Exception:
            raise CompoundRestoreRefused(
                "The candidate grant-state transition failed."
            ) from None
        return {"state": str(state), "runtime_role": self.runtime_role}

    def query_identity(self, sibling):
        try:
            with self._connect(sibling.database_url) as connection:
                live = query_live_database_identity(connection)
        except Exception:
            raise CompoundRestoreRefused(
                "The candidate live database identity query failed."
            ) from None
        endpoint = live.endpoint
        return ResourceIdentity(
            endpoint=f"{endpoint.host}:{endpoint.port}",
            database_name=endpoint.database,
            database_uuid=live.database_uuid,
            database_oid=live.oid,
            tls_identity=endpoint.tls_identity,
        )

    def marker_identity(self, sibling):
        try:
            with self._connect(sibling.database_url) as connection:
                live = query_live_database_identity(connection)
        except DatabaseIdentityError:
            try:
                with self._connect(sibling.database_url) as connection:
                    basic = _resource_identity(connection)
            except Exception:
                raise CompoundRestoreRefused(
                    "The sibling name/OID identity query failed."
                ) from None
            return DatabaseIdentity(
                basic.database_name,
                basic.database_oid,
            )
        except Exception:
            raise CompoundRestoreRefused(
                "The sibling server identity query failed."
            ) from None
        return DatabaseIdentity(
            live.endpoint.database,
            live.oid,
            live.server_identity(),
        )

    def owns(self, sibling, proof):
        if (
            not isinstance(proof, dict)
            or proof.get("created_by_this_run") is not True
            or proof.get("owner_marker") != sibling.owner_marker
        ):
            return False
        try:
            if self.query_identity(sibling).durable_key() != tuple(
                proof.get("identity", ())
            ):
                return False
            with self._connect() as admin, admin.cursor() as cursor:
                cursor.execute(
                    "SELECT shobj_description(oid, 'pg_database') "
                    "FROM pg_database WHERE datname=%s AND oid=%s",
                    [
                        sibling.identity.database_name,
                        sibling.identity.database_oid,
                    ],
                )
                row = cursor.fetchone()
        except Exception:
            return False
        return row is not None and row[0] == sibling.owner_marker
