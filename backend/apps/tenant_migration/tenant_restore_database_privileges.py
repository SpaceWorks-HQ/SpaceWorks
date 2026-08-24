"""Fail-closed PostgreSQL privilege probes for a D7 target sibling."""

from .tenant_restore_types import PrivilegeFacts


def probe_postgres_privileges(connection, *, runtime_role):
    """Return explicit false facts when a managed provider blocks any probe."""
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT rolsuper, rolcreatedb, rolcreaterole, "
                "pg_has_role(current_user, 'pg_signal_backend', 'MEMBER') "
                "FROM pg_roles WHERE rolname=current_user"
            )
            superuser, createdb, createrole, signal_backend = cursor.fetchone()
            cursor.execute(
                "SELECT has_schema_privilege(current_user, 'public', 'USAGE'), "
                "has_schema_privilege(current_user, 'public', 'CREATE'), "
                "pg_has_role(current_user, owner.rolname, 'MEMBER') "
                "FROM pg_namespace namespace JOIN pg_roles owner "
                "ON owner.oid=namespace.nspowner WHERE namespace.nspname='public'"
            )
            usage, create_schema, owns_schema = cursor.fetchone()
            cursor.execute(
                "SELECT EXISTS(SELECT 1 FROM pg_auth_members membership "
                "JOIN pg_roles target ON target.oid=membership.roleid "
                "JOIN pg_roles member ON member.oid=membership.member "
                "WHERE target.rolname=%s AND member.rolname=current_user "
                "AND membership.admin_option)",
                [runtime_role],
            )
            runtime_admin = cursor.fetchone()[0]
        return PrivilegeFacts(
            probed=True,
            can_create_database=bool(superuser or createdb),
            can_restore_schema=bool(usage and create_schema),
            can_apply_ownership=bool(superuser or owns_schema),
            can_apply_runtime_grants=bool(superuser or createrole or runtime_admin),
            can_exclude_sessions=bool(superuser or signal_backend),
        )
    except Exception:
        return PrivilegeFacts(False, False, False, False, False, False)
