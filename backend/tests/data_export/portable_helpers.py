import csv
import io
import zipfile
from datetime import timedelta
from pathlib import Path

from django.utils import timezone

from apps.accounts.models import User
from apps.data_export.models import DataExportJob
from apps.data_export.runner import build_archive
from apps.makerspaces.models import Makerspace


def make_user(username):
    return User.objects.create_user(
        username=username,
        email=f"{username}@example.test",
        access_status=User.AccessStatus.ACTIVE,
    )


def make_space(slug, *, pk=None):
    return Makerspace.objects.create(pk=pk, name=slug.replace("-", " ").title(), slug=slug)


def make_job(makerspace, actor, *, fidelity="PORTABLE", attach_approval=True):
    job = DataExportJob.objects.create(
        makerspace=makerspace,
        requested_by=actor,
        fidelity=fidelity,
        status=DataExportJob.Status.RUNNING,
        object_key=f"data-exports/{makerspace.pk}/{fidelity.lower()}-{timezone.now().timestamp()}.zip",
        deadline_at=timezone.now() + timedelta(minutes=5),
        expires_at=timezone.now() + timedelta(days=1),
    )
    if fidelity == "PORTABLE" and attach_approval:
        from apps.tenant_migration.admission import compute_pending_closure
        from apps.tenant_migration.models import (
            DisclosureClosureApproval,
            TenantMigrationExportJob,
        )

        closure = compute_pending_closure(makerspace)
        identity_ids = [str(item["id"]) for item in closure["identities"]]
        approval = DisclosureClosureApproval.objects.create(
            makerspace=makerspace,
            closure_digest=closure["digest"],
            identity_ids=identity_ids,
            approved_identity_ids=identity_ids,
            approved_by=actor,
        )
        TenantMigrationExportJob.objects.create(
            export_job=job,
            disclosure_approval=approval,
            closure_digest=approval.closure_digest,
            target_age_recipient="age1portablefixture000000000000",
        )
    return job


def archive_files(job):
    # build_archive returns shutil.make_archive's str path, not a Path.
    path, manifest, tempdir = build_archive(job, page_size=2)
    path = Path(path)
    try:
        archive_bytes = path.read_bytes()
        with zipfile.ZipFile(path) as archive:
            files = {name: archive.read(name) for name in archive.namelist()}
        return files, archive_bytes, manifest
    finally:
        tempdir.cleanup()


def csv_rows(files, name):
    return list(csv.DictReader(io.StringIO(files[name].decode("utf-8"))))
