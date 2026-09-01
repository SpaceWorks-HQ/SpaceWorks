"""Merge-staging and create-only promotion with an fsynced host journal."""

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path

from botocore.exceptions import BotoCoreError, ClientError
from django.conf import settings
from django.utils import timezone

from apps.backup import storage
from apps.backup.slice_merge_types import SliceMergeError
from apps.object_storage import delete_all_versions


@dataclass(frozen=True)
class StagedObject:
    component_id: object
    bucket_kind: str
    bucket: str
    staging_key: str
    final_key: str
    size: int
    sha256: str
    metadata: dict
    content_type: str
    headers: dict
    source: Path


class MergeJournal:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self.path.exists() and self.path.is_symlink():
            raise SliceMergeError("The merge journal path cannot be a symbolic link.")

    def append(self, effect, **facts):
        flags = os.O_APPEND | os.O_CREAT | os.O_WRONLY
        flags |= getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(self.path, flags, 0o600)
        try:
            os.fchmod(descriptor, 0o600)
            self._write(descriptor, effect, facts)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        directory = os.open(self.path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)

    def replace(self, effect, **facts):
        flags = os.O_TRUNC | os.O_CREAT | os.O_WRONLY
        flags |= getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(self.path, flags, 0o600)
        try:
            os.fchmod(descriptor, 0o600)
            self._write(descriptor, effect, facts)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        directory = os.open(self.path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)

    def events(self):
        if not self.path.exists():
            return ()
        try:
            return tuple(json.loads(line) for line in self.path.read_text().splitlines())
        except (OSError, json.JSONDecodeError):
            raise SliceMergeError("The host merge journal is unreadable.") from None

    @staticmethod
    def _write(descriptor, effect, facts):
        payload = json.dumps(
            {"at": timezone.now().isoformat(), "effect": effect, **facts},
            sort_keys=True, separators=(",", ":"), default=str,
        ).encode() + b"\n"
        view = memoryview(payload)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise SliceMergeError("The host merge journal could not be fsynced.")
            view = view[written:]


def stage_objects(validated_slices, operation_id, journal, *, accumulator=None):
    result = accumulator if accumulator is not None else []
    client = storage.client()
    try:
        for item in validated_slices:
            objects = item.manifest["storage"]["objects"]
            for ordinal, fact in enumerate(objects):
                bucket = _bucket(fact["bucket_kind"])
                stage_key = (
                    f"merge-staging/{operation_id}/{item.component.component_id}/"
                    f"{ordinal:08d}-{fact['sha256']}"
                )
                source = Path(item.root) / "objects" / fact["bucket_kind"] / fact["key"]
                journal.append(
                    "object_stage_intent", component_id=item.component.component_id,
                    bucket_kind=fact["bucket_kind"], staging_key=stage_key,
                    size=fact["size"], sha256=fact["sha256"],
                )
                staged = StagedObject(
                    component_id=item.component.component_id,
                    bucket_kind=fact["bucket_kind"], bucket=bucket,
                    staging_key=stage_key, final_key=fact["key"],
                    size=fact["size"], sha256=fact["sha256"],
                    metadata=fact.get("metadata") or {},
                    content_type=fact.get("content_type") or "",
                    headers=fact.get("headers") or {}, source=source,
                )
                result.append(staged)
                try:
                    with source.open("rb") as handle:
                        client.put_object(
                            Bucket=bucket, Key=stage_key, Body=handle,
                            ContentType="application/octet-stream", IfNoneMatch="*",
                        )
                except ClientError as exc:
                    status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
                    if status != 412:
                        raise
                _verify(client, staged.bucket, staged.staging_key, staged, metadata=False)
                journal.append(
                    "object_staged", component_id=staged.component_id,
                    bucket_kind=staged.bucket_kind, staging_key=staged.staging_key,
                    size=staged.size, sha256=staged.sha256,
                )
    except Exception as exc:
        cleanup_staging(result)
        if isinstance(exc, SliceMergeError):
            raise
        raise SliceMergeError("Object bytes could not be placed in merge staging.") from None
    return tuple(result)


def promote_objects(objects, journal):
    client = storage.client()
    promoted = []
    try:
        for item in objects:
            allow_existing = any(
                event.get("effect") == "object_promotion_intent"
                and event.get("bucket_kind") == item.bucket_kind
                and event.get("final_key") == item.final_key
                and event.get("sha256") == item.sha256
                for event in journal.events()
            )
            journal.append(
                "object_promotion_intent", component_id=item.component_id,
                bucket_kind=item.bucket_kind, staging_key=item.staging_key,
                final_key=item.final_key, size=item.size, sha256=item.sha256,
            )
            response = _create_final(client, item, allow_existing=allow_existing)
            _verify(client, item.bucket, item.final_key, item, metadata=True)
            version_id = response.get("VersionId", "")
            journal.append(
                "object_promoted", component_id=item.component_id,
                bucket_kind=item.bucket_kind, staging_key=item.staging_key,
                final_key=item.final_key, version_id=version_id,
                size=item.size, sha256=item.sha256,
            )
            promoted.append((item, version_id))
    except Exception:
        rollback_promoted(promoted, journal)
        raise SliceMergeError("A merge object could not be promoted fill-only.") from None
    return tuple(promoted)


def verify_promoted(objects):
    client = storage.client()
    for item in objects:
        _verify(client, item.bucket, item.final_key, item, metadata=True)


def cleanup_staging(objects, *, strict=False):
    client = storage.client()
    failures = []
    for item in objects:
        try:
            delete_all_versions(
                client, bucket=item.bucket, key=item.staging_key
            )
            if strict and not _absent(client, item.bucket, item.staging_key):
                failures.append(item.staging_key)
        except (BotoCoreError, ClientError):
            failures.append(item.staging_key)
    if strict and failures:
        raise SliceMergeError("Merge-staged plaintext objects could not be discarded.")


def rollback_promoted(promoted, journal):
    client = storage.client()
    for item, version_id in reversed(promoted):
        params = {"Bucket": item.bucket, "Key": item.final_key}
        if version_id:
            params["VersionId"] = version_id
        try:
            client.delete_object(**params)
            journal.append(
                "object_promotion_rolled_back", component_id=item.component_id,
                bucket_kind=item.bucket_kind, final_key=item.final_key,
                version_id=version_id,
            )
        except (BotoCoreError, ClientError):
            pass


def _create_final(client, item, *, allow_existing):
    response = client.get_object(Bucket=item.bucket, Key=item.staging_key)
    extra = {"Metadata": item.metadata, **item.headers}
    if item.content_type and "ContentType" not in extra:
        extra["ContentType"] = item.content_type
    try:
        return client.put_object(
            Bucket=item.bucket, Key=item.final_key, Body=response["Body"],
            IfNoneMatch="*", **extra,
        )
    except ClientError as exc:
        status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        if status == 412 and allow_existing:
            _verify(client, item.bucket, item.final_key, item, metadata=True)
            return {}
        if status == 412:
            raise SliceMergeError("A merge object destination is already occupied.") from None
        raise


def _verify(client, bucket, key, expected, *, metadata):
    try:
        response = client.get_object(Bucket=bucket, Key=key)
        digest = hashlib.sha256()
        size = 0
        while chunk := response["Body"].read(1024 * 1024):
            size += len(chunk)
            digest.update(chunk)
    except (BotoCoreError, ClientError, KeyError):
        raise SliceMergeError("A staged or promoted object is unreadable.") from None
    if size != expected.size or digest.hexdigest() != expected.sha256:
        raise SliceMergeError("A staged or promoted object failed byte verification.")
    if metadata and (
        (response.get("Metadata") or {}) != expected.metadata
        or (expected.content_type and response.get("ContentType") != expected.content_type)
        or any(response.get(name) != value for name, value in expected.headers.items())
    ):
        raise SliceMergeError("A promoted object failed metadata verification.")


def _bucket(kind):
    if kind == "private":
        return settings.AWS_STORAGE_BUCKET_NAME
    if kind == "public_image":
        return settings.PUBLIC_IMAGE_BUCKET
    raise SliceMergeError("The slice names an unsupported object bucket.")


def _absent(client, bucket, key):
    try:
        client.head_object(Bucket=bucket, Key=key)
        return False
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code")
        status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        if code in {"404", "NoSuchKey", "NotFound"} or status == 404:
            return True
        raise
