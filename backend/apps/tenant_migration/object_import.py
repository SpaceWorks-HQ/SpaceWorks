"""Stage, promote, checksum, and roll back imported tenant objects."""

from dataclasses import dataclass
import hashlib
import hmac
from pathlib import Path
import re

from django.db import transaction
from django.utils import timezone

from apps.audit import services as audit
from apps.backup.digests import sha256_file
from apps.makerspaces import limits

from .insertion_errors import ArchiveFormatError, ImportVerificationError
from .models_import_objects import TenantImportObject
from .object_export import object_member_path
from . import object_storage


SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class ObjectImportPlan:
    target_keys: dict[str, str]
    staged: int
    regenerated: int
    regenerated_keys: dict[str, str]


def prepare_import_objects(archive, job):
    records = _manifest_records(archive.root)
    target_keys = {}
    regenerated = 0
    regenerated_keys = {}
    for record in records:
        existing = TenantImportObject.objects.filter(
            job=job, source_key=record["source_key"]
        ).first()
        if existing is not None:
            _require_matching_journal(existing, record)
            target_keys[record["source_key"]] = existing.target_key
            regenerated += existing.target_key != existing.source_key
            if existing.target_key != existing.source_key:
                regenerated_keys[existing.source_key] = existing.target_key
            continue
        member = archive.root / object_member_path(
            record["bucket_kind"], record["source_key"]
        )
        _verify_local_member(member, record)
        staging_key = _staging_key(job.pk, record["source_key"])
        target_key, changed = object_storage.choose_target_key(
            record["bucket_kind"], record["source_key"], job.pk
        )
        object_storage.upload_staged(staging_key, member)
        staged_size, staged_sha = object_storage.digest_object("private", staging_key)
        if staged_size != record["size"] or not hmac.compare_digest(
            staged_sha, record["sha256"]
        ):
            object_storage.delete_object("private", staging_key)
            raise ImportVerificationError(
                f"Staged object checksum mismatch for {record['source_key']!r}."
            )
        TenantImportObject.objects.create(
            job=job,
            bucket_kind=record["bucket_kind"],
            source_key=record["source_key"],
            staging_key=staging_key,
            target_key=target_key,
            size=record["size"],
            sha256=record["sha256"],
        )
        target_keys[record["source_key"]] = target_key
        regenerated += changed
        if changed:
            regenerated_keys[record["source_key"]] = target_key
    _audit_staged(job, len(records), records)
    return ObjectImportPlan(
        target_keys, len(records), regenerated, regenerated_keys
    )


def promote_import_objects(job):
    promoted = 0
    rows = list(job.import_objects.order_by("pk"))
    for row in rows:
        if row.state == TenantImportObject.State.VERIFIED:
            continue
        if row.state != TenantImportObject.State.STAGED or row.claimed_at is not None:
            raise ImportVerificationError(
                f"Object {row.source_key!r} is not available for promotion."
            )
        claimed_at = timezone.now()
        claimed = TenantImportObject.objects.filter(
            pk=row.pk,
            state=TenantImportObject.State.STAGED,
            claimed_at__isnull=True,
        ).update(claimed_at=claimed_at)
        if claimed != 1:
            raise ImportVerificationError(
                f"Object {row.source_key!r} was claimed concurrently."
            )
        try:
            object_storage.copy_from_staging(
                row.staging_key, row.bucket_kind, row.target_key
            )
            _mark_promoted_and_charge(row.pk, job.target_makerspace)
            size, digest = object_storage.digest_object(row.bucket_kind, row.target_key)
            if size != row.size or not hmac.compare_digest(digest, row.sha256):
                raise ImportVerificationError(
                    f"Promoted object checksum mismatch for {row.source_key!r}."
                )
            TenantImportObject.objects.filter(
                pk=row.pk, state=TenantImportObject.State.PROMOTED
            ).update(state=TenantImportObject.State.VERIFIED, updated_at=timezone.now())
            promoted += 1
        except Exception:
            _clean_failed_promotion(row.pk, job.target_makerspace)
            raise
    _audit_promoted(job, promoted, rows)
    return promoted


@transaction.atomic
def _mark_promoted_and_charge(row_id, makerspace):
    row = TenantImportObject.objects.get(pk=row_id)
    if row.state != TenantImportObject.State.STAGED or row.claimed_at is None:
        raise ImportVerificationError("The object promotion claim is no longer valid.")
    limits.add_storage(makerspace, row.size)
    updated = TenantImportObject.objects.filter(
        pk=row_id,
        state=TenantImportObject.State.STAGED,
        claimed_at=row.claimed_at,
        quota_charged_at__isnull=True,
    ).update(
        state=TenantImportObject.State.PROMOTED,
        quota_charged_at=timezone.now(),
        updated_at=timezone.now(),
    )
    if updated != 1:
        raise ImportVerificationError("The object promotion claim was lost.")
    # Object copy happened before this transaction. A crash before this commit can
    # leave an unjournaled target copy, but the durable STAGED claim lets rollback
    # identify and delete it; quota and PROMOTED now either both commit or both roll back.


def _clean_failed_promotion(row_id, makerspace):
    row = TenantImportObject.objects.get(pk=row_id)
    object_storage.delete_object(row.bucket_kind, row.target_key)
    if row.quota_charged_at is not None:
        limits.free_storage(makerspace, row.size)
    TenantImportObject.objects.filter(pk=row_id).update(
        state=TenantImportObject.State.FAILED,
        quota_charged_at=None,
        updated_at=timezone.now(),
    )


def rollback_import_objects(job):
    rolled_back = 0
    for row in job.import_objects.exclude(
        state=TenantImportObject.State.ROLLED_BACK
    ).order_by("pk"):
        if row.claimed_at is not None or row.state in {
            TenantImportObject.State.PROMOTED,
            TenantImportObject.State.VERIFIED,
            TenantImportObject.State.FAILED,
        }:
            object_storage.delete_object(row.bucket_kind, row.target_key)
        object_storage.delete_object("private", row.staging_key)
        if row.quota_charged_at is not None and job.target_makerspace_id:
            limits.free_storage(job.target_makerspace, row.size)
        TenantImportObject.objects.filter(pk=row.pk).update(
            state=TenantImportObject.State.ROLLED_BACK,
            quota_charged_at=None,
            updated_at=timezone.now(),
        )
        rolled_back += 1
    if rolled_back:
        _audit_rolled_back(job, rolled_back)
    return rolled_back


def delete_staging_objects(job):
    for row in job.import_objects.all().only("staging_key"):
        object_storage.delete_object("private", row.staging_key)


def _manifest_records(root):
    path = Path(root) / "objects" / "manifest.jsonl"
    if not path.exists():
        return []
    import json

    records = []
    seen = set()
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ArchiveFormatError(
                    f"Invalid object manifest line {line_number}."
                ) from exc
            _validate_record(record, line_number)
            if record["source_key"] in seen:
                raise ArchiveFormatError("Object manifest source keys must be unique.")
            seen.add(record["source_key"])
            records.append(record)
    return records


def _validate_record(record, line_number):
    expected = {"bucket_kind", "source_key", "size", "sha256", "version_id"}
    if not isinstance(record, dict) or set(record) != expected:
        raise ArchiveFormatError(f"Invalid object manifest shape at line {line_number}.")
    if record["bucket_kind"] not in {"private", "public_image"}:
        raise ArchiveFormatError(f"Invalid object bucket at line {line_number}.")
    if not isinstance(record["source_key"], str) or not record["source_key"]:
        raise ArchiveFormatError(f"Invalid object key at line {line_number}.")
    if type(record["size"]) is not int or record["size"] < 0:
        raise ArchiveFormatError(f"Invalid object size at line {line_number}.")
    if not isinstance(record["sha256"], str) or not SHA256_RE.fullmatch(record["sha256"]):
        raise ArchiveFormatError(f"Invalid object checksum at line {line_number}.")
    if record["version_id"] is not None and not isinstance(record["version_id"], str):
        raise ArchiveFormatError(f"Invalid object version at line {line_number}.")


def _verify_local_member(path, record):
    if not path.is_file() or path.stat().st_size != record["size"]:
        raise ArchiveFormatError(f"Archive object is missing or truncated: {record['source_key']!r}.")
    if not hmac.compare_digest(sha256_file(path), record["sha256"]):
        raise ArchiveFormatError(f"Archive object checksum failed: {record['source_key']!r}.")


def _require_matching_journal(row, record):
    actual = (row.bucket_kind, row.size, row.sha256)
    expected = (record["bucket_kind"], record["size"], record["sha256"])
    if actual != expected or row.state == TenantImportObject.State.ROLLED_BACK:
        raise ImportVerificationError(
            f"Existing object journal conflicts with {record['source_key']!r}."
        )


def _staging_key(job_id, source_key):
    opaque = hashlib.sha256(source_key.encode("utf-8")).hexdigest()
    return f"tenant-imports/{job_id}/{opaque}"


def _aggregate_sha256(rows):
    checksums = sorted(
        row["sha256"] if isinstance(row, dict) else row.sha256 for row in rows
    )
    return hashlib.sha256("".join(checksums).encode("ascii")).hexdigest()


def _audit_staged(job, count, rows):
    audit.record(
        job.actor,
        "tenant_migration.objects_staged",
        makerspace=job.target_makerspace,
        target=job,
        meta={
            "job_id": str(job.pk),
            "object_count": count,
            "sha256": _aggregate_sha256(rows),
        },
    )


def _audit_promoted(job, count, rows):
    audit.record(
        job.actor,
        "tenant_migration.objects_promoted",
        makerspace=job.target_makerspace,
        target=job,
        meta={
            "job_id": str(job.pk),
            "object_count": count,
            "sha256": _aggregate_sha256(rows),
        },
    )


def _audit_rolled_back(job, count):
    audit.record(
        job.actor,
        "tenant_migration.objects_rolled_back",
        makerspace=job.target_makerspace,
        target=job,
        meta={
            "job_id": str(job.pk),
            "object_count": count,
            "sha256": _aggregate_sha256(()),
        },
    )
