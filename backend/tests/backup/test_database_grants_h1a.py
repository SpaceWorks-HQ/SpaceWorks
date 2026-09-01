import uuid

import pytest
from django.db import DatabaseError, connection, transaction
from psycopg2 import sql

from apps.backup.database_grants import GrantTarget, apply_grant_state, provision_runtime_role
from apps.backup.host_marker import MarkerState


@pytest.mark.django_db(transaction=True)
def test_database_refuses_bypassed_runtime_writer_during_candidate_preparation():
    suffix = uuid.uuid4().hex[:12]
    schema_name = f"h1a_{suffix}"
    role_name = f"h1a_runtime_{suffix}"
    target = GrantTarget(
        database=connection.settings_dict["NAME"],
        runtime_role=role_name,
        schema=schema_name,
    )
    with connection.cursor() as cursor:
        try:
            cursor.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema_name)))
            cursor.execute(sql.SQL("CREATE TABLE {}.probe (id integer primary key)").format(
                sql.Identifier(schema_name)
            ))
            provision_runtime_role(cursor, target, "test-only-password")
            apply_grant_state(cursor, target, MarkerState.CANDIDATE_PREPARATION)

            cursor.execute(sql.SQL("SET ROLE {}").format(sql.Identifier(role_name)))
            with pytest.raises(DatabaseError), transaction.atomic():
                cursor.execute(sql.SQL("INSERT INTO {}.probe VALUES (1)").format(
                    sql.Identifier(schema_name)
                ))
            cursor.execute("RESET ROLE")

            cursor.execute(sql.SQL("INSERT INTO {}.probe VALUES (2)").format(
                sql.Identifier(schema_name)
            ))
        finally:
            cursor.execute("RESET ROLE")
            cursor.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
                sql.Identifier(schema_name)
            ))
            cursor.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", [role_name])
            if cursor.fetchone():
                cursor.execute(sql.SQL("DROP OWNED BY {}").format(sql.Identifier(role_name)))
                cursor.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role_name)))
