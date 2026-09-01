"""The reconciler must count every charged object, and the purge must name every file.

Both of these fail SILENTLY, which is why they keep recurring: `recompute_storage` is the
authoritative total, so a model missing from it quietly lowers a space's recorded usage and
hands out free storage; a file missing from the purge's key collection simply outlives every
row that could identify it, with nothing raised at any point.
"""

from io import StringIO

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command

from apps.admin_api.models import BulkImportJob
from apps.machines.models import Machine, MachineType
from apps.maintenance.models import MaintenanceLog, MaintenanceLogDocument
from apps.makerspaces import lifecycle
from apps.makerspaces.models import Makerspace

pytestmark = pytest.mark.django_db


def make_space(slug):
    return Makerspace.objects.create(name=slug, slug=slug)


def make_actor(username):
    # `BulkImportJob.actor` is a non-null PROTECT FK, so these rows need a real user.
    return get_user_model().objects.create_user(
        username=username, email=f"{username}@example.test"
    )


def make_machine(makerspace, slug="recon-laser"):
    machine_type = MachineType.objects.create(
        makerspace=makerspace, slug=slug, name=slug.title()
    )
    return Machine.objects.create(
        makerspace=makerspace, machine_type=machine_type, name="Recon machine"
    )


def make_document(makerspace, *, size, index):
    machine = make_machine(makerspace, slug=f"recon-type-{index}")
    log = MaintenanceLog.objects.create(machine=machine, summary=f"Log {index}")
    return MaintenanceLogDocument.objects.create(
        log=log,
        object_key=f"maintenance/{makerspace.id}/doc-{index}.pdf",
        size_bytes=size,
    )


def test_recompute_storage_counts_maintenance_documents(monkeypatch):
    """They are charged on upload and collected by both purges, but were absent here --
    so the authoritative reconciler wrote a total that omitted every one of them."""
    makerspace = make_space("recon-maintenance-docs")
    make_document(makerspace, size=40, index=0)
    make_document(makerspace, size=60, index=1)
    # No object exists in storage under these keys, so the HEAD returns None and the
    # recorded `size_bytes` is the fallback -- the same contract as evidence rows.
    monkeypatch.setattr(
        "apps.maintenance.storage.object_size", lambda key: None
    )
    Makerspace.objects.filter(pk=makerspace.pk).update(storage_bytes_used=999)

    call_command("recompute_storage", makerspace.slug, stdout=StringIO())

    makerspace.refresh_from_db()
    assert makerspace.storage_bytes_used == 100


def test_purge_key_collection_names_bulk_import_uploads():
    """`BulkImportJob.upload` is a FileField on the S3 default storage, so its name is a
    key in the private bucket. The rows CASCADE away with the makerspace and nothing else
    records the file, so an uncollected upload outlives every row that could name it."""
    makerspace = make_space("recon-bulk-upload")
    job = BulkImportJob.objects.create(
        makerspace=makerspace,
        actor=make_actor("recon-bulk-actor"),
        mode=BulkImportJob.Mode.PREVIEW,
        upload="bulk-imports/2026/08/12/legacy.csv",
    )

    keys = lifecycle._collect_storage_keys(makerspace)

    assert job.upload.name in keys


def test_purge_key_collection_skips_jobs_without_an_upload():
    """Current jobs parse the file and store `rows`, leaving `upload` blank; a blank name
    must not enter the delete list as a falsy key."""
    makerspace = make_space("recon-bulk-no-upload")
    BulkImportJob.objects.create(
        makerspace=makerspace,
        actor=make_actor("recon-bulk-blank-actor"),
        mode=BulkImportJob.Mode.PREVIEW,
        upload="",
    )

    assert lifecycle._collect_storage_keys(makerspace) == []
