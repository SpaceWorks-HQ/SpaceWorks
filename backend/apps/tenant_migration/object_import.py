"""Stage, promote, checksum, and roll back imported tenant objects."""

from dataclasses import dataclass
import hashlib
import hmac
from pathlib import Path
import re

from django.utils import timezone

from apps.audit import services as audit
from apps.backup.digests import sha256_file
from apps.makerspaces import limits

from .insertion_errors import (
    ArchiveFormatError,
    ImportVerificationError,
)
from .models_import_objects import TenantImportObject
from .object_export import object_member_path
from .object_promotion import promote_import_objects
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
        if record.get("retention_state") == "expired":
            target_key, changed = object_storage.choose_target_key(
                record["bucket_kind"], record["source_key"], job.pk
            )
            target_keys[record["source_key"]] = target_key
            regenerated += changed
            if changed:
                regenerated_keys[record["source_key"]] = target_key
            continue
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
            content_type=record["content_type"],
        )
        target_keys[record["source_key"]] = target_key
        regenerated += changed
        if changed:
            regenerated_keys[record["source_key"]] = target_key
    live_records = [row for row in records if row.get("retention_state") != "expired"]
    _audit_staged(job, len(live_records), live_records)
    return ObjectImportPlan(
        target_keys, len(live_records), regenerated, regenerated_keys
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
            record["content_type"] = record.get("content_type") or ""
            if record["source_key"] in seen:
                raise ArchiveFormatError("Object manifest source keys must be unique.")
            seen.add(record["source_key"])
            records.append(record)
    return records


def _validate_record(record, line_number):
    required = {"bucket_kind", "source_key", "size", "sha256", "version_id"}
    tombstone_fields = {
        "retention_state", "object_expired_at", "expired_size_bytes"
    }
    allowed = required | {"content_type"} | tombstone_fields
    if (
        not isinstance(record, dict)
        or not required.issubset(record)
        or not set(record).issubset(allowed)
    ):
        raise ArchiveFormatError(f"Invalid object manifest shape at line {line_number}.")
    if record["bucket_kind"] not in {"private", "public_image"}:
        raise ArchiveFormatError(f"Invalid object bucket at line {line_number}.")
    if not isinstance(record["source_key"], str) or not record["source_key"]:
        raise ArchiveFormatError(f"Invalid object key at line {line_number}.")
    expired = record.get("retention_state") == "expired"
    if expired and not tombstone_fields.issubset(record):
        raise ArchiveFormatError(f"Incomplete expiry tombstone at line {line_number}.")
    if not expired and tombstone_fields & set(record):
        raise ArchiveFormatError(f"Unexpected expiry fields at line {line_number}.")
    if type(record["size"]) is not int or record["size"] < 0:
        raise ArchiveFormatError(f"Invalid object size at line {line_number}.")
    if expired and (record["size"] != 0 or record["sha256"] != ""):
        raise ArchiveFormatError(f"Invalid expiry tombstone at line {line_number}.")
    if not expired and (
        not isinstance(record["sha256"], str)
        or not SHA256_RE.fullmatch(record["sha256"])
    ):
        raise ArchiveFormatError(f"Invalid object checksum at line {line_number}.")
    if record["version_id"] is not None and not isinstance(record["version_id"], str):
        raise ArchiveFormatError(f"Invalid object version at line {line_number}.")
    content_type = record.get("content_type")
    if content_type is not None and (
        not isinstance(content_type, str) or len(content_type) > 255
    ):
        raise ArchiveFormatError(f"Invalid object content type at line {line_number}.")
    if expired:
        if not isinstance(record["object_expired_at"], str):
            raise ArchiveFormatError(f"Invalid expiry timestamp at line {line_number}.")
        expired_size = record["expired_size_bytes"]
        if expired_size is not None and (
            type(expired_size) is not int or expired_size < 0
        ):
            raise ArchiveFormatError(f"Invalid expired size at line {line_number}.")


def _verify_local_member(path, record):
    if not path.is_file() or path.stat().st_size != record["size"]:
        raise ArchiveFormatError(f"Archive object is missing or truncated: {record['source_key']!r}.")
    if not hmac.compare_digest(sha256_file(path), record["sha256"]):
        raise ArchiveFormatError(f"Archive object checksum failed: {record['source_key']!r}.")


def _require_matching_journal(row, record):
    actual = (row.bucket_kind, row.size, row.sha256, row.content_type)
    expected = (
        record["bucket_kind"],
        record["size"],
        record["sha256"],
        record["content_type"],
    )
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
