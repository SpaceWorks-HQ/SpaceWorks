"""Bounded storage operations for tenant-import staging and promotion."""

import hashlib
from pathlib import Path
import uuid

from botocore.exceptions import BotoCoreError, ClientError
from django.conf import settings

from apps.backup.storage import client


CHUNK_SIZE = 1024 * 1024


class TenantObjectStorageError(RuntimeError):
    pass


def bucket_name(bucket_kind):
    if bucket_kind == "private":
        return settings.AWS_STORAGE_BUCKET_NAME
    if bucket_kind == "public_image":
        return settings.PUBLIC_IMAGE_BUCKET
    raise TenantObjectStorageError(f"Unsupported bucket kind: {bucket_kind!r}.")


def upload_staged(staging_key, path):
    try:
        with Path(path).open("rb") as handle:
            client().upload_fileobj(
                handle,
                settings.AWS_STORAGE_BUCKET_NAME,
                staging_key,
                ExtraArgs={"ContentType": "application/octet-stream"},
            )
    except (BotoCoreError, ClientError, OSError) as exc:
        raise TenantObjectStorageError(
            f"Could not stage tenant import object {staging_key!r}."
        ) from exc


def copy_from_staging(staging_key, bucket_kind, target_key):
    try:
        client().copy_object(
            Bucket=bucket_name(bucket_kind),
            CopySource={
                "Bucket": settings.AWS_STORAGE_BUCKET_NAME,
                "Key": staging_key,
            },
            Key=target_key,
        )
    except (BotoCoreError, ClientError) as exc:
        raise TenantObjectStorageError(
            f"Could not promote tenant import object {target_key!r}."
        ) from exc


def digest_object(bucket_kind, object_key):
    try:
        response = client().get_object(
            Bucket=bucket_name(bucket_kind),
            Key=object_key,
        )
        digest = hashlib.sha256()
        size = 0
        body = response["Body"]
        try:
            while chunk := body.read(CHUNK_SIZE):
                size += len(chunk)
                digest.update(chunk)
        finally:
            body.close()
        return size, digest.hexdigest()
    except (BotoCoreError, ClientError, OSError) as exc:
        raise TenantObjectStorageError(
            f"Could not verify tenant import object {object_key!r}."
        ) from exc


def object_exists(bucket_kind, object_key):
    try:
        client().head_object(Bucket=bucket_name(bucket_kind), Key=object_key)
        return True
    except ClientError as exc:
        error = exc.response.get("Error", {}).get("Code")
        status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        if error in {"404", "NoSuchKey", "NotFound"} or status == 404:
            return False
        raise TenantObjectStorageError(
            f"Could not inspect target object {object_key!r}."
        ) from exc
    except BotoCoreError as exc:
        raise TenantObjectStorageError(
            f"Could not inspect target object {object_key!r}."
        ) from exc


def choose_target_key(bucket_kind, source_key, job_id):
    if not object_exists(bucket_kind, source_key):
        return source_key, False
    for _attempt in range(16):
        candidate = f"migrated-objects/{job_id}/{uuid.uuid4().hex}"
        if not object_exists(bucket_kind, candidate):
            return candidate, True
    raise TenantObjectStorageError("Could not allocate a collision-safe target key.")


def delete_object(bucket_kind, object_key):
    if not object_key:
        return
    try:
        client().delete_object(Bucket=bucket_name(bucket_kind), Key=object_key)
    except (BotoCoreError, ClientError) as exc:
        raise TenantObjectStorageError(
            f"Could not delete tenant import object {object_key!r}."
        ) from exc


def list_staging_keys(job_id):
    prefix = f"tenant-imports/{job_id}/"
    keys = []
    token = None
    try:
        while True:
            params = {"Bucket": settings.AWS_STORAGE_BUCKET_NAME, "Prefix": prefix}
            if token:
                params["ContinuationToken"] = token
            page = client().list_objects_v2(**params)
            keys.extend(item["Key"] for item in page.get("Contents", ()))
            if not page.get("IsTruncated"):
                return set(keys)
            token = page.get("NextContinuationToken")
    except (BotoCoreError, ClientError) as exc:
        raise TenantObjectStorageError(
            f"Could not enumerate staging namespace for import {job_id}."
        ) from exc
