import pytest
from django.db import connection

from apps.tenant_migration.tenant_dump_sequences import normalize_sequences


pytestmark = pytest.mark.django_db(transaction=True)


def test_normalized_sequences_emit_max_plus_one_for_populated_and_one_for_empty():
    with connection.cursor() as cursor:
        cursor.execute("CREATE TABLE lane_d8_nonempty (id bigserial PRIMARY KEY)")
        cursor.execute("CREATE TABLE lane_d8_empty (id bigserial PRIMARY KEY)")
        cursor.execute("INSERT INTO lane_d8_nonempty (id) VALUES (41)")
    try:
        state = normalize_sequences("default")
        with connection.cursor() as cursor:
            cursor.execute("SELECT nextval('lane_d8_nonempty_id_seq')")
            populated_next = cursor.fetchone()[0]
            cursor.execute("SELECT nextval('lane_d8_empty_id_seq')")
            empty_next = cursor.fetchone()[0]

        assert state["public.lane_d8_nonempty_id_seq"] == (41, True)
        assert state["public.lane_d8_empty_id_seq"] == (1, False)
        assert populated_next == 42
        assert empty_next == 1
    finally:
        with connection.cursor() as cursor:
            cursor.execute("DROP TABLE lane_d8_nonempty")
            cursor.execute("DROP TABLE lane_d8_empty")
