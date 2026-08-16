import csv
import io
import json
import zipfile
from datetime import timedelta

import pytest
from django.core.management import call_command
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.audit import services as audit
from apps.data_export.models import DataExportJob
from apps.data_export.runner import build_archive
from apps.data_export.services import run_export_job
from apps.inventory.models import Category, InventoryProduct
from apps.makerspaces import lifecycle, limits
from apps.makerspaces.models import Makerspace

pytestmark = pytest.mark.django_db(transaction=True)


def user(name):
    return User.objects.create_user(username=name, access_status=User.AccessStatus.ACTIVE)


def space(slug, creator=None):
    return Makerspace.objects.create(name=slug, slug=slug, created_by=creator)


def job_for(makerspace, actor):
    return DataExportJob.objects.create(
        makerspace=makerspace,
        requested_by=actor,
        fidelity="REDACTED",
        status=DataExportJob.Status.RUNNING,
        object_key=f"data-exports/{makerspace.pk}/{timezone.now().timestamp()}.zip",
        deadline_at=timezone.now() + timedelta(minutes=5),
        expires_at=timezone.now() + timedelta(days=1),
    )


def archive_files(job, *, page_size=2):
    path, manifest, tempdir = build_archive(job, page_size=page_size)
    try:
        with zipfile.ZipFile(path) as archive:
            return {name: archive.read(name) for name in archive.namelist()}, manifest
    finally:
        tempdir.cleanup()


def csv_rows(files, name):
    return list(csv.DictReader(io.StringIO(files[name].decode("utf-8"))))


def test_two_tenant_export_excludes_foreign_rows_values_and_unrelated_users():
    referenced = user("referenced-local")
    audit_actor = user("referenced-auditor")
    requester = user("job-requester-not-a-source-edge")
    unrelated = user("unrelated-global")
    foreign_actor = user("FOREIGN-USER-SENTINEL")
    local = space("local-export", referenced)
    foreign = space("FOREIGN-SPACE-SENTINEL", foreign_actor)
    InventoryProduct.objects.create(
        makerspace=local, name="Local drill", total_quantity=1, available_quantity=1
    )
    InventoryProduct.objects.create(
        makerspace=foreign, name="FOREIGN-PRODUCT-SENTINEL",
        total_quantity=1, available_quantity=1,
    )
    audit.record(audit_actor, "export.fixture", makerspace=local, target=local)

    files, _manifest = archive_files(job_for(local, requester))
    flattened = b"\n".join(files.values()).decode("utf-8")
    users = csv_rows(files, "global/users.csv")

    assert "Local drill" in flattened
    assert "FOREIGN-PRODUCT-SENTINEL" not in flattened
    assert "FOREIGN-SPACE-SENTINEL" not in flattened
    assert "FOREIGN-USER-SENTINEL" not in flattened
    assert {row["username"] for row in users} == {
        referenced.username,
        audit_actor.username,
    }
    assert unrelated.username not in flattened
    assert requester.username not in flattened
    assert set(users[0]) == {"id", "username"}


def test_keyset_paging_returns_every_row_exactly_once():
    actor = user("paging-actor")
    makerspace = space("paging-space")
    for index in range(7):
        Category.objects.create(
            makerspace=makerspace, name=f"Category {index}", slug=f"c-{index}"
        )
    expected = set(
        Category.objects.filter(makerspace=makerspace).values_list("pk", flat=True)
    )

    files, manifest = archive_files(job_for(makerspace, actor), page_size=2)
    rows = csv_rows(files, "inventory/categories.csv")
    ids = [int(row["id"]) for row in rows]

    assert set(ids) == expected
    assert len(ids) == len(set(ids)) == len(expected)
    assert manifest["row_counts"]["inventory/categories.csv"] == len(expected)


def test_deadline_exhaustion_is_typed_and_never_uploads(settings, monkeypatch):
    settings.DATA_EXPORT_DEADLINE_SECONDS = 0
    actor = user("deadline-actor")
    makerspace = space("deadline-space")
    job = DataExportJob.objects.create(
        makerspace=makerspace,
        requested_by=actor,
        fidelity="REDACTED",
        object_key=f"data-exports/{makerspace.pk}/deadline.zip",
        expires_at=timezone.now() + timedelta(days=1),
    )
    uploads = []
    monkeypatch.setattr("apps.data_export.storage.upload_archive", lambda *args: uploads.append(args))
    monkeypatch.setattr("apps.data_export.storage.delete_object", lambda key: True)

    run_export_job(job.pk)
    job.refresh_from_db()

    assert job.status == DataExportJob.Status.FAILED
    assert job.failure_code == DataExportJob.FailureCode.DEADLINE_EXCEEDED
    assert job.manifest["deadline"]["outcome"] == "exhausted"
    assert job.accounted_size_bytes == 0
    assert uploads == []


def test_archive_is_charged_released_collected_and_recomputed(monkeypatch):
    actor = user("storage-actor")
    makerspace = space("export-storage")
    makerspace.resource_limit_overrides = {"storage": 10_000_000}
    makerspace.save(update_fields=("resource_limit_overrides",))
    monkeypatch.setattr(limits, "is_self_host", lambda: False)
    job = job_for(makerspace, actor)
    job.status = DataExportJob.Status.AVAILABLE
    job.accounted_size_bytes = 321
    job.save(update_fields=("status", "accounted_size_bytes"))
    limits.add_storage(makerspace, 321)

    assert job.object_key in lifecycle._collect_storage_keys(makerspace)

    monkeypatch.setattr("apps.data_export.storage.object_size", lambda key: 321)
    call_command("recompute_storage", makerspace.slug)
    makerspace.refresh_from_db()
    assert makerspace.storage_bytes_used == 321

    monkeypatch.setattr("apps.data_export.storage.delete_object", lambda key: True)
    with transaction.atomic():
        job.delete()
    makerspace.refresh_from_db()
    assert makerspace.storage_bytes_used == 0
