"""Remote byte operations for backup staging and create-only promotion."""

import hashlib
import hmac

from botocore.exceptions import BotoCoreError, ClientError
from django.conf import settings


CHUNK_SIZE = 1024 * 1024


def staging_locator(artifact_id):
    return f"backup-archives/staging/{artifact_id}.tar.age"


def final_locator(artifact_id):
    return f"backup-archives/deployment/{artifact_id}.tar.age"


def upload_staging(key, path):
    from apps.backup import storage

    storage.upload_archive(key, path)


def stream_verify(key, *, expected_size, expected_sha256):
    from apps.backup import storage

    body = None
    try:
        body = storage.client().get_object(
            Bucket=settings.AWS_STORAGE_BUCKET_NAME, Key=key
        )["Body"]
        digest = hashlib.sha256()
        size = 0
        while chunk := body.read(CHUNK_SIZE):
            size += len(chunk)
            digest.update(chunk)
    except (BotoCoreError, ClientError, OSError) as exc:
        raise storage.BackupStorageError(
            "The backup archive could not be streamed for verification."
        ) from exc
    finally:
        if body is not None and hasattr(body, "close"):
            body.close()
    actual = digest.hexdigest()
    if size != expected_size or not hmac.compare_digest(actual, expected_sha256):
        raise storage.BackupVerificationError(
            "The stored backup archive does not match its expected size and sha256."
        )
    return size, actual


def create_final_from_staging(staging_key, final_key):
    """Stream staging into a destination protected by `If-None-Match: *`."""
    from apps.backup import storage

    source = None
    try:
        s3 = storage.client()
        source = s3.get_object(
            Bucket=settings.AWS_STORAGE_BUCKET_NAME, Key=staging_key
        )["Body"]
        s3.put_object(
            Bucket=settings.AWS_STORAGE_BUCKET_NAME,
            Key=final_key,
            Body=source,
            ContentType="application/octet-stream",
            IfNoneMatch="*",
        )
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code")
        status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        if code in {"PreconditionFailed", "ConditionalRequestConflict"} or status in {
            409, 412
        }:
            raise storage.BackupStorageError(
                "The immutable final backup locator already exists."
            ) from exc
        raise storage.BackupStorageError(
            "The backup staging object could not be promoted."
        ) from exc
    except BotoCoreError as exc:
        raise storage.BackupStorageError(
            "The backup staging object could not be promoted."
        ) from exc
    finally:
        if source is not None and hasattr(source, "close"):
            source.close()


def object_exists(key):
    from apps.backup import storage

    try:
        storage.client().head_object(
            Bucket=settings.AWS_STORAGE_BUCKET_NAME, Key=key
        )
        return True
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code")
        status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        if code in {"404", "NoSuchKey", "NotFound"} or status == 404:
            return False
        raise storage.BackupStorageError(
            "The backup object locator could not be inspected."
        ) from exc
    except BotoCoreError as exc:
        raise storage.BackupStorageError(
            "The backup object locator could not be inspected."
        ) from exc
