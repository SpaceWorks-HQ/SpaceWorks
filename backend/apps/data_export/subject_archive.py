"""Bounded JSON/ZIP projection using the existing export field dispositions."""

import json
import tempfile
import time
import zipfile
from dataclasses import replace
from pathlib import Path

from django.apps import apps
from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder
from django.db import connection, transaction
from django.utils import timezone

from . import REGISTRY_VERSION
from .archive import source_value, transform_value
from .datasets import DATASETS
from .fields import EXTERNAL_REFERENCES
from .runner import ExportDeadlineExceeded
from .subject_selectors import subject_query
from .types import Fidelity, Redacted


def project_subject_row(dataset, row, subject_id):
    result = {}
    for column in dataset.columns:
        source = column.sources[0]
        if "__" in source:
            # Derived other-actor names never enter a subject's global-user closure.
            continue
        value = source_value(row, source)
        model_field = row._meta.get_field(source)
        related = getattr(model_field, "related_model", None)
        if related is not None and related._meta.label == "accounts.User":
            value = value if value == subject_id else None
        if source.endswith("_actor_snapshot"):
            value = None
        if (dataset.model, source) in EXTERNAL_REFERENCES:
            # A cross-space routing reference is outside this subject's tenant.
            result[column.name] = None
            continue
        disposition = column.disposition
        if dataset.model == "audit.AuditLog":
            if source == "meta":
                disposition = Redacted("meta_redacted")
            if source == "target_id" and not (
                row.target_type == "accounts.user" and str(value) == str(subject_id)
            ):
                value = None
        # PORTABLE classifies safe readable columns and omits all credentials. Here
        # getters decrypt scoped PII for its owner; no encrypted migration blobs or
        # raw PII collector are needed, and no related person is expanded.
        result[column.name] = transform_value(
            dataset.model, source, disposition, value, row=row,
        )
    return result


def build_subject_archive(job, *, monotonic=time.monotonic):
    tempdir = tempfile.TemporaryDirectory(prefix="spaceworks-subject-")
    path = Path(tempdir.name, "subject.zip")
    remaining = max(0, (job.deadline_at - timezone.now()).total_seconds())
    deadline = monotonic() + remaining
    counts = {}
    try:
        with transaction.atomic(), zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
            with connection.cursor() as cursor:
                cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
                cursor.execute("SET LOCAL statement_timeout = %s", [max(1, int(remaining * 1000))])
                cursor.execute("SET LOCAL lock_timeout = %s", [max(1, int(remaining * 1000))])
            snapshot = timezone.now()
            for dataset in DATASETS.values():
                if dataset.fidelity is not Fidelity.PORTABLE:
                    continue
                # Preserve the reviewed fields, but use the ordinary plaintext getter
                # instead of the PORTABLE archive's encryption/remapping machinery.
                dataset = replace(dataset, fidelity=Fidelity.REDACTED)
                model = apps.get_model(dataset.model)
                query = subject_query(model, job.requested_by, job.makerspace_id)
                count = 0
                with archive.open(dataset.path.removesuffix(".csv") + ".json", "w") as output:
                    output.write(b"[")
                    for row in query.order_by("pk").iterator(chunk_size=settings.DATA_EXPORT_PAGE_SIZE):
                        if monotonic() >= deadline:
                            raise ExportDeadlineExceeded(dataset.path, sum(counts.values()) + count)
                        value = project_subject_row(dataset, row, job.requested_by_id)
                        if count:
                            output.write(b",")
                        output.write(json.dumps(value, cls=DjangoJSONEncoder, ensure_ascii=False).encode())
                        count += 1
                    output.write(b"]")
                counts[dataset.model] = count
            manifest = {
                "kind": "subject_access", "registry_version": REGISTRY_VERSION,
                "makerspace_id": job.makerspace_id, "subject_id": job.requested_by_id,
                "snapshot_at": snapshot.isoformat(), "row_counts": counts,
                "total_rows": sum(counts.values()),
                "omissions": "Credentials, other people's identities, tenant configuration, "
                             "anonymous records without proven ownership, and photo/file bytes.",
            }
            archive.writestr("manifest.json", json.dumps(manifest, cls=DjangoJSONEncoder))
        return path, manifest, tempdir
    except Exception:
        tempdir.cleanup()
        raise
