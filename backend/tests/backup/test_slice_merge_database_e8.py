import uuid

import pytest
from django.db import DatabaseError, connection, transaction

from apps.backup.models import B1RestoreComponentState, B1RestoreOperationState
from apps.backup.slice_merge_database import (
    MERGE_ROLE,
    merge_schema_name,
    protect_target_tables,
    provision_merge_role,
)
from apps.inventory.models import Category
from apps.makerspaces.models import Makerspace


pytestmark = pytest.mark.django_db(transaction=True)


def _merging_component():
    operation_id = uuid.uuid4()
    artifact_id = uuid.uuid4()
    capture_id = uuid.uuid4()
    operation = B1RestoreOperationState.objects.create(
        operation_id=operation_id, artifact_id=artifact_id, capture_id=capture_id,
        main_component_id=uuid.uuid4(), outer_ciphertext_sha256="a" * 64,
        outer_manifest_sha256="b" * 64, source_proof_sha256="c" * 64,
        sibling_database_name="e8_role_test", sibling_database_oid=88,
        sibling_server_identity="postgresql:e8-test",
    )
    for stage in (
        B1RestoreOperationState.Stage.MAIN_RESTORED,
        B1RestoreOperationState.Stage.ROLES_RECREATED,
        B1RestoreOperationState.Stage.STATE_REHYDRATED,
        B1RestoreOperationState.Stage.ENFORCEMENT_INSTALLED,
        B1RestoreOperationState.Stage.CATALOG_VERIFIED,
        B1RestoreOperationState.Stage.OBJECTS_VERIFIED,
        B1RestoreOperationState.Stage.QUARANTINE_VERIFIED,
        B1RestoreOperationState.Stage.CUTOVER_READY,
    ):
        B1RestoreOperationState.objects.filter(pk=operation.pk).update(stage=stage)
    component = B1RestoreComponentState.objects.create(
        operation_id=operation_id, artifact_id=artifact_id, capture_id=capture_id,
        component_id=uuid.uuid4(), makerspace_id_snapshot=800008,
        ciphertext_sha256="d" * 64, state=B1RestoreComponentState.State.PENDING,
    )
    B1RestoreComponentState.objects.filter(pk=component.pk).update(state="merging")
    component.refresh_from_db()
    return operation, component


def _stage_context(operation, component, category):
    schema = merge_schema_name(operation.operation_id, [component.component_id])
    with connection.cursor() as cursor:
        cursor.execute(f'CREATE SCHEMA "{schema}"')
        cursor.execute(
            f'CREATE TABLE "{schema}".backup_b1_context '
            '(operation_id uuid NOT NULL, component_id uuid PRIMARY KEY)'
        )
        cursor.execute(
            f'INSERT INTO "{schema}".backup_b1_context VALUES (%s, %s)',
            [operation.operation_id, component.component_id],
        )
        cursor.execute(
            f'CREATE TABLE "{schema}".backup_b1_deltas ('
            'component_id uuid, table_name text, row_pk jsonb, column_name text, '
            'old_value jsonb, new_value jsonb)'
        )
        cursor.execute(
            f'CREATE TABLE "{schema}".inventory_category '
            '(LIKE public.inventory_category INCLUDING GENERATED)'
        )
        cursor.execute(
            f'ALTER TABLE "{schema}".inventory_category '
            'ADD COLUMN __b1_component_id uuid NOT NULL'
        )
        cursor.execute(
            f'INSERT INTO "{schema}".inventory_category '
            '(id, makerspace_id, name, slug, display_order, icon, created_at, updated_at, '
            '__b1_component_id) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)',
            [category.pk, category.makerspace_id, "occupied replacement", category.slug,
             category.display_order, category.icon, category.created_at, category.updated_at,
             component.component_id],
        )
    provision_merge_role()
    protect_target_tables(schema, {"inventory_category"})
    return schema


def _set_role(cursor, operation, component, schema):
    cursor.execute(f"SET LOCAL ROLE {MERGE_ROLE}")
    cursor.execute("SELECT set_config('app.b1_merge_operation', %s, true)", [str(operation.operation_id)])
    cursor.execute("SELECT set_config('app.b1_merge_component', %s, true)", [str(component.component_id)])
    cursor.execute("SELECT set_config('app.b1_merge_schema', %s, true)", [schema])


def test_merge_role_cannot_overwrite_update_or_setval():
    operation, component = _merging_component()
    space = Makerspace.objects.create(name="E8 role target", slug="e8-role-target")
    category = Category.objects.create(makerspace=space, name="occupied", slug="occupied")
    schema = _stage_context(operation, component, category)
    try:
        with pytest.raises(DatabaseError), transaction.atomic():
            with connection.cursor() as cursor:
                _set_role(cursor, operation, component, schema)
                cursor.execute(
                    "INSERT INTO inventory_category "
                    "(id, makerspace_id, name, slug, display_order, icon, created_at, updated_at) "
                    f"SELECT id, makerspace_id, name, slug, display_order, icon, created_at, updated_at "
                    f'FROM "{schema}".inventory_category'
                )
        with pytest.raises(DatabaseError), transaction.atomic():
            with connection.cursor() as cursor:
                _set_role(cursor, operation, component, schema)
                cursor.execute("UPDATE inventory_category SET name = 'outside delta' WHERE id = %s", [category.pk])
        with pytest.raises(DatabaseError), transaction.atomic():
            with connection.cursor() as cursor:
                _set_role(cursor, operation, component, schema)
                cursor.execute("SELECT setval(pg_get_serial_sequence('inventory_category', 'id'), 999999)")
    finally:
        with connection.cursor() as cursor:
            cursor.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
