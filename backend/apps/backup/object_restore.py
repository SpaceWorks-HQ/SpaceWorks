"""Copy-on-write object restore with an external, fsynced swap journal."""

from datetime import timedelta
import json
import os
from pathlib import Path, PurePosixPath

from botocore.exceptions import ClientError
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.backup import object_restore_versions, storage
from apps.backup.models import RestoreOperation, RestoreRollbackObject
from apps.backup.object_restore_versions import ObjectRestoreError
from apps.makerspaces import limits
from apps.makerspaces.models import Makerspace
from apps.object_storage import delete_all_versions


def restore_objects(restore, bundle_root, manifest, journal_path):
    root = Path(bundle_root).resolve()
    journal = Path(journal_path)
    restored = []
    for item in manifest.get("storage", {}).get("objects", []):
        key = _safe_key(item["key"])
        kind = item["bucket_kind"]
        source = (root / "objects" / kind / key).resolve()
        if root not in source.parents or not source.is_file():
            raise ObjectRestoreError(f"Archive object is missing or unsafe: {key}")
        rollback = _prepare_rollback(restore, item, journal)
        try:
            replacement_version = _upload_replacement(item, source)
        except Exception:
            rollback_objects(restore)
            raise
        rollback.replacement_version_id = replacement_version
        rollback.save(update_fields=("replacement_version_id",))
        _journal(journal, {"effect": "replacement_written", "row_id": rollback.pk, "version_id": replacement_version})
        restored.append(rollback)
    return restored


def _prepare_rollback(restore, item, journal):
    key = _safe_key(item["key"])
    kind = item["bucket_kind"]
    bucket = _bucket(kind)
    client = storage.client()
    versioned = storage.ensure_versioning_or_quiescence(bucket) == "versioned"
    current = _head(client, bucket, key)
    copy_key = ""
    source_version = (current or {}).get("VersionId", "") if versioned else ""
    absent = current is None
    absent_marker_version = (
        object_restore_versions.current_delete_marker_version_id(client, bucket, key)
        if versioned and absent
        else ""
    )
    if not versioned and not absent:
        copy_key = f"rollback/{restore.pk}/{kind}/{key}"
    maker_id = item.get("makerspace_id")
    row = RestoreRollbackObject.objects.create(
        restore=restore,
        makerspace_id=maker_id,
        bucket_kind=kind,
        module_key=item.get("module_key", ""),
        source_key=key,
        copy_key=copy_key,
        source_was_absent=absent,
        source_absent_marker_version_id=absent_marker_version,
        source_version_id=source_version,
        expires_at=timezone.now() + timedelta(days=7),
    )
    _journal(journal, {
        "effect": "rollback_intent", "row_id": row.pk, "bucket": bucket,
        "bucket_kind": kind, "makerspace_id": maker_id,
        "module_key": row.module_key, "size_bytes": 0,
        "source_key": key, "copy_key": copy_key, "absent": absent,
        "source_absent_marker_version_id": absent_marker_version,
        "source_version_id": source_version,
    })
    if copy_key:
        try:
            response = client.copy_object(
                Bucket=bucket,
                CopySource={"Bucket": bucket, "Key": key},
                Key=copy_key,
                MetadataDirective="COPY",
            )
            size = int(current.get("ContentLength") or 0)
            maker = Makerspace.objects.filter(pk=maker_id).first() if maker_id else None
            if maker:
                try:
                    limits.add_storage(maker, size)
                except Exception:
                    delete_all_versions(client, bucket=bucket, key=copy_key)
                    raise
            row.size_bytes = size
            row.save(update_fields=("size_bytes",))
            _journal(journal, {
                "effect": "rollback_copy_created",
                "row_id": row.pk,
                "etag": response.get("CopyObjectResult", {}).get("ETag", ""),
                "size_bytes": size,
            })
        except Exception as exc:
            row.delete()
            raise ObjectRestoreError(f"Could not preserve {kind}:{key}; nothing was overwritten.") from exc
    return row


def _upload_replacement(item, source):
    kind, key = item["bucket_kind"], _safe_key(item["key"])
    bucket = _bucket(kind)
    extra = {"Metadata": item.get("metadata") or {}, **(item.get("headers") or {})}
    if item.get("content_type") and "ContentType" not in extra:
        extra["ContentType"] = item["content_type"]
    with source.open("rb") as handle:
        storage.client().upload_fileobj(handle, bucket, key, ExtraArgs=extra)
    return (_head(storage.client(), bucket, key) or {}).get("VersionId", "")


def rollback_objects(restore):
    client = storage.client()
    for row in restore.rollback_objects.select_related("makerspace").order_by("-pk"):
        bucket = _bucket(row.bucket_kind)
        if row.replacement_version_id:
            client.delete_object(Bucket=bucket, Key=row.source_key, VersionId=row.replacement_version_id)
        elif row.source_version_id:
            # A host interruption can land after a versioned upload succeeds but
            # before its returned version id reaches the journal.  Writers are still
            # excluded, so a different current version is the unrecorded replacement.
            current = _head(client, bucket, row.source_key)
            current_version = (current or {}).get("VersionId", "")
            if current_version and current_version != row.source_version_id:
                client.delete_object(
                    Bucket=bucket, Key=row.source_key, VersionId=current_version
                )
        elif row.source_was_absent:
            if row.source_absent_marker_version_id:
                object_restore_versions.delete_versions_newer_than_marker(
                    client,
                    bucket=bucket,
                    key=row.source_key,
                    marker_version_id=row.source_absent_marker_version_id,
                )
            else:
                delete_all_versions(client, bucket=bucket, key=row.source_key)
        elif row.copy_key:
            client.copy_object(
                Bucket=bucket,
                CopySource={"Bucket": bucket, "Key": row.copy_key},
                Key=row.source_key,
                MetadataDirective="COPY",
            )


def cleanup_rollback_objects(restore):
    client = storage.client()
    for row in restore.rollback_objects.select_related("makerspace"):
        if row.copy_key:
            delete_all_versions(
                client, bucket=_bucket(row.bucket_kind), key=row.copy_key
            )
        elif row.source_version_id:
            client.delete_object(
                Bucket=_bucket(row.bucket_kind),
                Key=row.source_key,
                VersionId=row.source_version_id,
            )
        if row.makerspace_id and row.size_bytes:
            limits.free_storage(row.makerspace, row.size_bytes)
        row.delete()


def cleanup_expired_rollback_objects(limit=100):
    """Remove expired failed-restore copies without deleting a live source version."""
    rows = list(
        RestoreRollbackObject.objects.select_related("makerspace", "restore")
        .filter(expires_at__lte=timezone.now())
        .order_by("pk")[:limit]
    )
    cleaned = 0
    for row in rows:
        if row.copy_key:
            try:
                delete_all_versions(
                    storage.client(),
                    bucket=_bucket(row.bucket_kind),
                    key=row.copy_key,
                )
            except Exception:
                continue
        elif row.source_version_id and row.restore.stage in {
            RestoreOperation.Stage.COMPLETED,
            RestoreOperation.Stage.RESTORED_QUARANTINED,
        }:
            try:
                storage.client().delete_object(
                    Bucket=_bucket(row.bucket_kind),
                    Key=row.source_key,
                    VersionId=row.source_version_id,
                )
            except Exception:
                continue
        with transaction.atomic():
            locked = (
                RestoreRollbackObject.objects.select_for_update()
                .select_related("makerspace")
                .filter(pk=row.pk, expires_at__lte=timezone.now())
                .first()
            )
            if locked is None:
                continue
            if locked.makerspace_id and locked.size_bytes:
                limits.free_storage(locked.makerspace, locked.size_bytes)
            locked.delete()
            cleaned += 1
    return cleaned


def reconcile_rollback_journal(restore, journal_path):
    """Recreate object ownership rows after either database outcome."""
    path = Path(journal_path)
    if not path.exists():
        return 0
    intents = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        event = json.loads(line)
        row_id = event.get("row_id")
        if event.get("effect") == "rollback_intent":
            intents[row_id] = event
        elif row_id in intents and event.get("effect") == "rollback_copy_created":
            intents[row_id]["copy_created"] = True
            intents[row_id]["size_bytes"] = int(event.get("size_bytes") or 0)
        elif row_id in intents and event.get("effect") == "replacement_written":
            intents[row_id]["replacement_version_id"] = event.get("version_id", "")
    valid = []
    for event in intents.values():
        if event.get("copy_key") and not event.get("copy_created"):
            existing = _head(storage.client(), event["bucket"], event["copy_key"])
            if existing is None:
                continue
            event["size_bytes"] = int(existing.get("ContentLength") or 0)
        valid.append(event)
    for event in valid:
        RestoreRollbackObject.objects.update_or_create(
            restore=restore,
            bucket_kind=event["bucket_kind"],
            source_key=event["source_key"],
            defaults={
                "makerspace_id": event.get("makerspace_id"),
                "module_key": event.get("module_key", ""),
                "copy_key": event.get("copy_key", ""),
                "source_was_absent": bool(event.get("absent")),
                "source_absent_marker_version_id": event.get(
                    "source_absent_marker_version_id", ""
                ),
                "source_version_id": event.get("source_version_id", ""),
                "replacement_version_id": event.get("replacement_version_id", ""),
                "size_bytes": int(event.get("size_bytes") or 0),
                "expires_at": timezone.now() + timedelta(days=7),
            },
        )
    return len(valid)


def _head(client, bucket, key):
    try:
        return client.head_object(Bucket=bucket, Key=key)
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code")
        status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        if code in {"404", "NoSuchKey", "NotFound"} or status == 404:
            return None
        raise


def _journal(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"at": timezone.now().isoformat(), **payload}, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def _safe_key(value):
    path = PurePosixPath(str(value))
    if path.is_absolute() or not path.parts or ".." in path.parts:
        raise ObjectRestoreError("Archive contains an unsafe object key.")
    return path.as_posix()


def _bucket(kind):
    if kind == RestoreRollbackObject.BucketKind.PRIVATE:
        return settings.AWS_STORAGE_BUCKET_NAME
    if kind == RestoreRollbackObject.BucketKind.PUBLIC_IMAGE:
        return settings.PUBLIC_IMAGE_BUCKET
    raise ObjectRestoreError(f"Unknown bucket kind: {kind}")
