import pytest
from django.contrib.auth import get_user_model
from django.db import connection, transaction

from apps.backup.raw_projection import raw_records
from apps.hardware_requests.models import HardwareRequest, HardwareRequestItem
from apps.inventory.models import InventoryProduct
from apps.makerspaces.models import Makerspace

from apps.tenant_migration.tenant_dump_errors import TenantDumpVerificationError
from apps.tenant_migration.tenant_dump_sql import (
    delete_portable_rows,
    insert_rows,
    verify_foreign_key_closure,
    verify_tables_empty,
)
from apps.tenant_migration.tenant_dump_graph import plan_row_load
from apps.tenant_migration.tenant_dump_raw import sanitize_record
from apps.tenant_migration.tenant_dump_sequences import normalize_sequences


pytestmark = pytest.mark.django_db(transaction=True)


def test_reverse_fk_delete_and_topological_load_keep_constraints_enabled():
    makerspace = Makerspace.objects.create(name="D2 constraint lab", slug="d2-constraint-lab")
    product = InventoryProduct.objects.create(
        makerspace=makerspace,
        name="Constraint fixture",
        total_quantity=1,
        available_quantity=1,
    )
    requester = get_user_model().objects.create_user(username="d2-constraint-requester")
    request = HardwareRequest.objects.create(
        makerspace=makerspace,
        requester=requester,
        requester_username=requester.username,
        requested_for="D2 constrained projection",
    )
    item = HardwareRequestItem.objects.create(
        request=request,
        product=product,
        requested_quantity=1,
    )
    models = (HardwareRequest, HardwareRequestItem)
    source = [
        *raw_records(HardwareRequest.objects.filter(pk=request.pk), HardwareRequest),
        *raw_records(HardwareRequestItem.objects.filter(pk=item.pk), HardwareRequestItem),
    ]
    rows = [
        sanitize_record(HardwareRequest, source[0]),
        sanitize_record(HardwareRequestItem, source[1]),
    ]

    with transaction.atomic():
        delete_portable_rows("default", makerspace.pk, models)
        assert not HardwareRequest.objects.filter(pk=request.pk).exists()
        plan = plan_row_load(rows)
        assert plan.used_two_pass is False
        assert [row.model for row in plan.rows] == [
            HardwareRequest,
            HardwareRequestItem,
        ]
        insert_rows("default", plan.rows)

    assert HardwareRequestItem.objects.get(pk=item.pk).request_id == request.pk


def test_post_load_schema_walk_rejects_a_deliberately_broken_fk():
    with connection.cursor() as cursor:
        cursor.execute("CREATE TABLE lane_d_parent (id bigint PRIMARY KEY)")
        cursor.execute(
            "CREATE TABLE lane_d_child (id bigint PRIMARY KEY, parent_id bigint NOT NULL)"
        )
        cursor.execute("INSERT INTO lane_d_child (id, parent_id) VALUES (1, 999)")
        cursor.execute(
            "ALTER TABLE lane_d_child ADD CONSTRAINT lane_d_child_parent_fk "
            "FOREIGN KEY (parent_id) REFERENCES lane_d_parent(id) NOT VALID"
        )
    try:
        with pytest.raises(TenantDumpVerificationError, match="Dangling FK closure"):
            verify_foreign_key_closure("default")
    finally:
        with connection.cursor() as cursor:
            cursor.execute("DROP TABLE lane_d_child")
            cursor.execute("DROP TABLE lane_d_parent")


def test_sequence_normalization_covers_nonempty_and_empty_tables():
    with connection.cursor() as cursor:
        cursor.execute("CREATE TABLE lane_d_nonempty (id bigserial PRIMARY KEY)")
        cursor.execute("CREATE TABLE lane_d_empty (id bigserial PRIMARY KEY)")
        cursor.execute("INSERT INTO lane_d_nonempty (id) VALUES (41)")
    try:
        state = normalize_sequences("default")
        assert state["public.lane_d_nonempty_id_seq"] == (41, True)
        assert state["public.lane_d_empty_id_seq"] == (1, False)
    finally:
        with connection.cursor() as cursor:
            cursor.execute("DROP TABLE lane_d_nonempty")
            cursor.execute("DROP TABLE lane_d_empty")


def test_cache_postcondition_refuses_populated_runtime_data():
    with connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO spaceworks_cache (cache_key, value, expires) "
            "VALUES ('lane-d', %s, CURRENT_TIMESTAMP + INTERVAL '1 hour')",
            ["source-runtime-row"],
        )
    with pytest.raises(TenantDumpVerificationError, match="spaceworks_cache"):
        verify_tables_empty("default", {"spaceworks_cache"})
