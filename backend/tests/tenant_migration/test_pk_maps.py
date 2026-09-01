import uuid

import pytest
from django.db import connection, transaction
from django.test.utils import CaptureQueriesContext

from apps.inventory.models import Category
from apps.tenant_migration.models import TenantImportJob
from apps.tenant_migration.pk_maps import TABLE_NAME, TransactionPkMap


pytestmark = pytest.mark.django_db(transaction=True)


def test_preallocation_is_bulk_real_unique_and_transaction_local():
    integer_sources = [f"category-{index}" for index in range(5)]
    uuid_sources = [f"job-{index}" for index in range(3)]

    with transaction.atomic():
        pk_map = TransactionPkMap()
        with CaptureQueriesContext(connection) as queries:
            pk_map.reserve(Category, iter(integer_sources), batch_size=2)
        pk_map.reserve(TenantImportJob, iter(uuid_sources), batch_size=2)

        integer_targets = [pk_map.lookup(Category, source) for source in integer_sources]
        uuid_targets = [pk_map.lookup(TenantImportJob, source) for source in uuid_sources]
        assert len(set(integer_targets)) == len(integer_targets)
        assert len(set(uuid_targets)) == len(uuid_targets)
        assert all(isinstance(target, int) for target in integer_targets)
        assert all(isinstance(target, uuid.UUID) for target in uuid_targets)
        assert not Category.objects.filter(pk__in=integer_targets).exists()
        assert not TenantImportJob.objects.filter(pk__in=uuid_targets).exists()

        sequence_queries = [
            query["sql"] for query in queries.captured_queries
            if "nextval(pg_get_serial_sequence" in query["sql"]
        ]
        assert len(sequence_queries) == 3
        with connection.cursor() as cursor:
            cursor.execute("SELECT to_regclass(%s)", [f"pg_temp.{TABLE_NAME}"])
            assert cursor.fetchone()[0] is not None

    with connection.cursor() as cursor:
        cursor.execute("SELECT to_regclass(%s)", [f"pg_temp.{TABLE_NAME}"])
        assert cursor.fetchone()[0] is None
