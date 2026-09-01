import uuid

import pytest
from django.db import connection, transaction
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.hardware_requests.models import HardwareRequest
from apps.inventory.models import Category
from apps.makerspaces.models import Makerspace
from apps.tenant_migration.insertion_errors import TenantImportFenceRequired
from apps.tenant_migration.pk_maps import TransactionPkMap
from apps.tenant_migration.raw_repository import RawImportRepository


pytestmark = pytest.mark.django_db(transaction=True)


def _category_row(pk, makerspace_id, slug):
    now = timezone.now()
    return {
        "id": pk,
        "makerspace_id": makerspace_id,
        "name": slug.replace("-", " ").title(),
        "slug": slug,
        "display_order": 0,
        "icon": "",
        "created_at": now,
        "updated_at": now,
    }


def test_repository_inserts_explicit_primary_keys_in_bounded_batches():
    space = Makerspace.objects.create(
        name="Raw Repository", slug=f"raw-repository-{uuid.uuid4().hex[:8]}"
    )
    source_ids = ["source-one", "source-two"]
    with transaction.atomic():
        pk_map = TransactionPkMap()
        pk_map.reserve(Category, source_ids)
        target_ids = [pk_map.lookup(Category, source_id) for source_id in source_ids]
        rows = (
            _category_row(target_pk, space.pk, f"imported-{index}-{uuid.uuid4().hex[:6]}")
            for index, target_pk in enumerate(target_ids)
        )
        with CaptureQueriesContext(connection) as queries:
            inserted = RawImportRepository().insert_rows(
                Category, rows, batch_size=1
            )

    inserts = [
        query["sql"]
        for query in queries.captured_queries
        if query["sql"].startswith('INSERT INTO "inventory_category"')
    ]
    assert inserted == 2
    assert len(inserts) == 2
    inserted_ids = Category.objects.filter(pk__in=target_ids).values_list(
        "pk", flat=True
    )
    assert set(inserted_ids) == set(target_ids)


def test_repository_refuses_mapped_model_without_active_import_fence():
    with transaction.atomic(), pytest.raises(TenantImportFenceRequired):
        RawImportRepository().insert_rows(HardwareRequest, [{"id": 1}])


def test_repository_never_commits_a_partial_import():
    space = Makerspace.objects.create(
        name="Raw Rollback", slug=f"raw-rollback-{uuid.uuid4().hex[:8]}"
    )
    slug = f"must-rollback-{uuid.uuid4().hex[:8]}"

    with pytest.raises(RuntimeError, match="later import failure"):
        with transaction.atomic():
            pk_map = TransactionPkMap()
            pk_map.reserve(Category, ["rollback-source"])
            target_pk = pk_map.lookup(Category, "rollback-source")
            RawImportRepository().insert_rows(
                Category, [_category_row(target_pk, space.pk, slug)]
            )
            raise RuntimeError("later import failure")

    assert not Category.objects.filter(slug=slug, makerspace=space).exists()
