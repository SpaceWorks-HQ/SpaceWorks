"""Private storage for age-encrypted archives."""

import hashlib
import logging

import boto3
from botocore.client import Config
from botocore.exceptions import BotoCoreError, ClientError
from django.conf import settings

from apps.object_storage import delete_all_versions

logger = logging.getLogger(__name__)

# Shared by every uploader: apps.*.storage.staging_key() is f"staging/{final_key}".
STAGING_PREFIX = "staging/"

RESTORABLE_HEADERS = (
    "CacheControl", "ContentDisposition", "ContentEncoding", "ContentLanguage",
    "ContentType", "Expires", "WebsiteRedirectLocation",
)


class BackupStorageError(RuntimeError):
    pass


class BackupVerificationError(BackupStorageError):
    pass


def client(*, public_endpoint=False):
    endpoint = settings.AWS_S3_PUBLIC_ENDPOINT_URL if public_endpoint else settings.AWS_S3_ENDPOINT_URL
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
        aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
        region_name=settings.AWS_S3_REGION_NAME,
        config=Config(
            signature_version=settings.AWS_S3_SIGNATURE_VERSION,
            s3={"addressing_style": settings.AWS_S3_ADDRESSING_STYLE},
        ),
    )


def upload_archive(key, path):
    try:
        with open(path, "rb") as handle:
            client().upload_fileobj(
                handle,
                settings.AWS_STORAGE_BUCKET_NAME,
                key,
                ExtraArgs={"ContentType": "application/octet-stream"},
            )
    except (BotoCoreError, ClientError, OSError) as exc:
        raise BackupStorageError("The encrypted backup archive could not be stored.") from exc


def open_archive(key):
    try:
        return client(public_endpoint=True).get_object(
            Bucket=settings.AWS_STORAGE_BUCKET_NAME, Key=key
        )["Body"]
    except (BotoCoreError, ClientError) as exc:
        raise BackupStorageError("The encrypted backup archive could not be opened.") from exc


def delete_archive(key):
    try:
        s3 = client()
        delete_all_versions(
            s3, bucket=settings.AWS_STORAGE_BUCKET_NAME, key=key
        )
        return True
    except (BotoCoreError, ClientError):
        logger.exception("backup_archive_delete_failed", extra={"object_key": key})
        return False


def ensure_versioning_or_quiescence(bucket):
    """Return versioned when the backend can guarantee version IDs, else quiesced."""
    s3 = client()
    try:
        status = s3.get_bucket_versioning(Bucket=bucket).get("Status")
        if status == "Enabled":
            return "versioned"
        s3.put_bucket_versioning(
            Bucket=bucket, VersioningConfiguration={"Status": "Enabled"}
        )
        status = s3.get_bucket_versioning(Bucket=bucket).get("Status")
        return "versioned" if status == "Enabled" else "quiesced"
    except (BotoCoreError, ClientError):
        return "quiesced"


def download_object(bucket, key, destination, *, versioned):
    """Capture one object, falling back to its staging copy.

    Every uploader presigns `staging/{key}` and only promotes the bytes to `key`
    when a workflow consumes them, so an uploaded-but-unconsumed object exists
    ONLY in staging while its row already names the final key. Capture used to
    treat that as fatal, meaning a single pending upload could block a tenant
    backup or migration. The staged bytes are recorded under the FINAL key so a
    restore lands them where every app's read path looks first; promotion still
    validates them, because each finalizer validates the final object when it
    finds one.
    """
    try:
        return _download_object(bucket, key, destination, versioned=versioned)
    except BackupStorageError:
        if key.startswith(STAGING_PREFIX):
            raise
        staged = _download_object(
            bucket, f"{STAGING_PREFIX}{key}", destination, versioned=versioned
        )
        logger.warning(
            "backup_captured_staged_object",
            extra={"bucket": bucket, "key": key},
        )
        return {**staged, "key": key}


def _download_object(bucket, key, destination, *, versioned):
    s3 = client()
    params = {"Bucket": bucket, "Key": key}
    version_id = ""
    try:
        if versioned:
            try:
                version_id = s3.head_object(**params).get("VersionId") or ""
            except ClientError as exc:
                code = exc.response.get("Error", {}).get("Code")
                status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
                if code not in {"404", "NoSuchKey", "NotFound"} and status != 404:
                    raise
                version_id = _latest_retained_version(s3, bucket, key)
            if not version_id:
                raise BackupStorageError(f"Version-enabled bucket returned no version id for {key}.")
            params["VersionId"] = version_id
        response = s3.get_object(**params)
        destination.parent.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256()
        with destination.open("wb") as handle:
            while chunk := response["Body"].read(1024 * 1024):
                handle.write(chunk)
                digest.update(chunk)
        return {
            "key": key,
            "version_id": version_id,
            "size": destination.stat().st_size,
            "sha256": digest.hexdigest(),
            "metadata": response.get("Metadata", {}),
            "content_type": response.get("ContentType", ""),
            "headers": {
                name: response[name] for name in RESTORABLE_HEADERS
                if name in response and response[name] not in (None, "")
            },
        }
    except BackupStorageError:
        raise
    except (BotoCoreError, ClientError, OSError) as exc:
        raise BackupStorageError(f"Could not capture storage object {key}.") from exc


def _latest_retained_version(s3, bucket, key):
    key_marker = version_marker = None
    while True:
        params = {"Bucket": bucket, "Prefix": key}
        if key_marker:
            params["KeyMarker"] = key_marker
        if version_marker:
            params["VersionIdMarker"] = version_marker
        page = s3.list_object_versions(**params)
        versions = [
            item for item in page.get("Versions", []) if item.get("Key") == key
        ]
        if versions:
            newest = max(versions, key=lambda item: item.get("LastModified"))
            return newest.get("VersionId") or ""
        if not page.get("IsTruncated"):
            return ""
        key_marker = page.get("NextKeyMarker")
        version_marker = page.get("NextVersionIdMarker")


from .storage_promotion import create_final_from_staging, final_locator, object_exists, staging_locator, stream_verify, upload_staging  # noqa: E402,F401
