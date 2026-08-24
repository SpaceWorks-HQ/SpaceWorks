"""PostgreSQL runtime-role provisioning and state-specific grant transitions."""

from __future__ import annotations

from dataclasses import dataclass

from psycopg2 import sql

from .host_marker import MarkerState


class DatabaseGrantError(RuntimeError):
    pass


WRITABLE_STATES = frozenset({
    MarkerState.NORMAL,
    MarkerState.QUARANTINED_AFTER_CUTOVER,
    MarkerState.ACKNOWLEDGED_NORMAL,
})


@dataclass(frozen=True, slots=True)
class GrantTarget:
    database: str
    runtime_role: str
    schema: str = "public"


def _role_exists(cursor, role):
    cursor.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", [role])
    return cursor.fetchone() is not None


def fence_runtime_login(cursor, role_name):
    """Immediately prevent new logins and terminate every existing runtime session."""
    if not _role_exists(cursor, role_name):
        return
    role = sql.Identifier(role_name)
    cursor.execute(sql.SQL("ALTER ROLE {} NOLOGIN").format(role))
    cursor.execute(
        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
        "WHERE usename = %s AND pid <> pg_backend_pid()",
        [role_name],
    )


def _assert_narrow_runtime_role(cursor, role):
    cursor.execute(
        "SELECT rolsuper, rolcreaterole, rolcreatedb, rolreplication, rolbypassrls "
        "FROM pg_roles WHERE rolname = %s",
        [role],
    )
    row = cursor.fetchone()
    if row is None or any(row):
        raise DatabaseGrantError("Runtime database role is missing or privileged.")
    cursor.execute(
        "SELECT EXISTS (SELECT 1 FROM pg_auth_members memberships "
        "JOIN pg_roles member ON member.oid = memberships.member WHERE member.rolname = %s) "
        "OR EXISTS (SELECT 1 FROM pg_database database JOIN pg_roles owner "
        "ON owner.oid = database.datdba WHERE owner.rolname = %s) "
        "OR EXISTS (SELECT 1 FROM pg_namespace namespace JOIN pg_roles owner "
        "ON owner.oid = namespace.nspowner WHERE owner.rolname = %s) "
        "OR EXISTS (SELECT 1 FROM pg_class relation JOIN pg_roles owner "
        "ON owner.oid = relation.relowner WHERE owner.rolname = %s) "
        "OR EXISTS (SELECT 1 FROM pg_proc function JOIN pg_roles owner "
        "ON owner.oid = function.proowner WHERE owner.rolname = %s)",
        [role, role, role, role, role],
    )
    if cursor.fetchone()[0]:
        raise DatabaseGrantError("Runtime database role owns objects or inherits another role.")


def provision_runtime_role(cursor, target, password):
    """Create/re-key a non-owner runtime role and establish future-object defaults."""
    if not password or "\x00" in password:
        raise DatabaseGrantError("Runtime database password is missing or invalid.")
    cursor.execute("SELECT current_user")
    maintenance_role = cursor.fetchone()[0]
    if maintenance_role == target.runtime_role:
        raise DatabaseGrantError("Maintenance and runtime database roles must be distinct.")
    role = sql.Identifier(target.runtime_role)
    if not _role_exists(cursor, target.runtime_role):
        cursor.execute(sql.SQL("CREATE ROLE {} NOLOGIN PASSWORD %s").format(role), [password])
    else:
        cursor.execute(sql.SQL("ALTER ROLE {} NOLOGIN").format(role))
        cursor.execute(sql.SQL("ALTER ROLE {} PASSWORD %s").format(role), [password])
    cursor.execute(sql.SQL("ALTER ROLE {} NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE "
                           "NOREPLICATION NOBYPASSRLS").format(role))
    _assert_narrow_runtime_role(cursor, target.runtime_role)
    schema = sql.Identifier(target.schema)
    cursor.execute(sql.SQL("REVOKE CREATE ON SCHEMA {} FROM PUBLIC").format(schema))
    cursor.execute(sql.SQL("GRANT USAGE ON SCHEMA {} TO {}").format(schema, role))
    cursor.execute(sql.SQL("ALTER DEFAULT PRIVILEGES IN SCHEMA {} "
                           "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {}").format(schema, role))
    cursor.execute(sql.SQL("ALTER DEFAULT PRIVILEGES IN SCHEMA {} "
                           "GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO {}").format(schema, role))
    cursor.execute(sql.SQL("ALTER DEFAULT PRIVILEGES IN SCHEMA {} "
                           "GRANT EXECUTE ON FUNCTIONS TO {}").format(schema, role))


def _assert_effectively_read_only(cursor, target):
    cursor.execute(
        "SELECT EXISTS (SELECT 1 FROM pg_class relation "
        "JOIN pg_namespace namespace ON namespace.oid = relation.relnamespace "
        "WHERE namespace.nspname = %s AND relation.relkind IN ('r', 'p') AND ("
        "has_table_privilege(%s, relation.oid, 'INSERT') OR "
        "has_table_privilege(%s, relation.oid, 'UPDATE') OR "
        "has_table_privilege(%s, relation.oid, 'DELETE') OR "
        "has_table_privilege(%s, relation.oid, 'TRUNCATE'))) "
        "OR EXISTS (SELECT 1 FROM pg_class sequence "
        "JOIN pg_namespace namespace ON namespace.oid = sequence.relnamespace "
        "WHERE namespace.nspname = %s AND sequence.relkind = 'S' AND ("
        "has_sequence_privilege(%s, sequence.oid, 'USAGE') OR "
        "has_sequence_privilege(%s, sequence.oid, 'UPDATE')))",
        [target.schema, target.runtime_role, target.runtime_role, target.runtime_role,
         target.runtime_role, target.schema, target.runtime_role, target.runtime_role],
    )
    if cursor.fetchone()[0]:
        raise DatabaseGrantError("Runtime database role still has an effective write privilege.")


def apply_grant_state(cursor, target, state):
    """Apply the database boundary independently from any process entrypoint."""
    state = MarkerState(state)
    _assert_narrow_runtime_role(cursor, target.runtime_role)
    role = sql.Identifier(target.runtime_role)
    schema = sql.Identifier(target.schema)
    database = sql.Identifier(target.database)
    login = state != MarkerState.CANDIDATE_PREPARATION
    if not login:
        # Privileged host callers use autocommit, so NOLOGIN becomes authoritative
        # before session termination and privilege cleanup. The marker is already
        # restrictive at this point.
        fence_runtime_login(cursor, target.runtime_role)
    cursor.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(database, role))
    cursor.execute(sql.SQL("GRANT USAGE ON SCHEMA {} TO {}").format(schema, role))
    cursor.execute(sql.SQL("GRANT SELECT ON ALL TABLES IN SCHEMA {} TO {}").format(schema, role))
    cursor.execute(sql.SQL("GRANT SELECT ON ALL SEQUENCES IN SCHEMA {} TO {}").format(schema, role))
    cursor.execute(sql.SQL("GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA {} TO {}").format(schema, role))
    cursor.execute(sql.SQL("REVOKE INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER "
                           "ON ALL TABLES IN SCHEMA {} FROM {}").format(schema, role))
    cursor.execute(sql.SQL("REVOKE USAGE, UPDATE ON ALL SEQUENCES IN SCHEMA {} FROM {}").format(schema, role))
    if state in WRITABLE_STATES:
        cursor.execute(sql.SQL("GRANT INSERT, UPDATE, DELETE "
                               "ON ALL TABLES IN SCHEMA {} TO {}").format(schema, role))
        cursor.execute(sql.SQL("GRANT USAGE, UPDATE ON ALL SEQUENCES IN SCHEMA {} TO {}").format(schema, role))
    else:
        _assert_effectively_read_only(cursor, target)
    if login:
        cursor.execute(sql.SQL("ALTER ROLE {} LOGIN").format(role))
