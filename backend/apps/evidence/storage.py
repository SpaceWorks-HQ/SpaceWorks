from dataclasses import dataclass
import logging
import uuid

import boto3
from botocore.client import Config
from botocore.exceptions import BotoCoreError, ClientError
from django.conf import settings

from apps.evidence.image_validation import image_mime_from_bytes
from apps.object_storage import delete_all_versions


logger = logging.getLogger(__name__)


class StorageUnavailable(Exception):
    pass


class EvidenceObjectValidationError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class EvidenceValidationResult:
    size: int
    content_type: str

def _s3_client(endpoint_url):
    return boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
        aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
        region_name=settings.AWS_S3_REGION_NAME,
        config=Config(
            signature_version=settings.AWS_S3_SIGNATURE_VERSION,
            s3={"addressing_style": settings.AWS_S3_ADDRESSING_STYLE},
        ),
    )


def _client():
    return _s3_client(settings.AWS_S3_ENDPOINT_URL)


def _public_client():
    return _s3_client(settings.AWS_S3_PUBLIC_ENDPOINT_URL)


def evidence_object_key(makerspace_id, evidence_type):
    return f"evidence/{makerspace_id}/{evidence_type}/{uuid.uuid4().hex}"


def staging_key(final_key):
    return f"staging/{final_key}"


def delete_object(object_key):
    try:
        delete_all_versions(
            _client(), bucket=settings.AWS_STORAGE_BUCKET_NAME, key=object_key
        )
    except (BotoCoreError, ClientError):
        logger.exception("Failed to delete storage object %s.", object_key)


def delete_object_strict(object_key):
    """Delete every version and report whether a current object was visible."""
    existed = object_exists(object_key)
    try:
        delete_all_versions(
            _client(),
            bucket=settings.AWS_STORAGE_BUCKET_NAME,
            key=object_key,
            require_version_listing=True,
        )
    except (BotoCoreError, ClientError) as exc:
        raise StorageUnavailable from exc
    return "deleted" if existed else "absent_or_version_only"


def copy_object(source_key, dest_key):
    try:
        _client().copy_object(
            Bucket=settings.AWS_STORAGE_BUCKET_NAME,
            CopySource={
                "Bucket": settings.AWS_STORAGE_BUCKET_NAME,
                "Key": source_key,
            },
            Key=dest_key,
        )
    except (BotoCoreError, ClientError) as exc:
        raise StorageUnavailable from exc


def finalize_upload(evidence, max_bytes):
    from apps.evidence.finalization import FinalizationInProgress
    from apps.evidence.finalization import finalize_upload as finalize_evidence_upload

    try:
        return finalize_evidence_upload(evidence, max_bytes)
    except FinalizationInProgress as exc:
        raise StorageUnavailable from exc


def presigned_upload(object_key, content_type):
    try:
        if settings.STORAGE_PRESIGN_METHOD == "put":
            # Presigned PUT cannot enforce content-length at upload time; finalize HEADs staging.
            url = _public_client().generate_presigned_url(
                "put_object",
                Params={
                    "Bucket": settings.AWS_STORAGE_BUCKET_NAME,
                    "Key": staging_key(object_key),
                    "ContentType": content_type,
                },
                ExpiresIn=settings.EVIDENCE_URL_TTL_SECONDS,
            )
            return {
                "url": url,
                "method": "PUT",
                "headers": {"Content-Type": content_type},
            }
        return _public_client().generate_presigned_post(
            Bucket=settings.AWS_STORAGE_BUCKET_NAME,
            Key=staging_key(object_key),
            Fields={"Content-Type": content_type},
            Conditions=[
                {"Content-Type": content_type},
                ["content-length-range", 1, settings.EVIDENCE_MAX_BYTES],
            ],
            ExpiresIn=settings.EVIDENCE_URL_TTL_SECONDS,
        )
    except (BotoCoreError, ClientError) as exc:
        raise StorageUnavailable from exc


def validate_evidence_object(object_key):
    size = object_size(object_key)
    if size is None:
        raise EvidenceObjectValidationError("missing", "Evidence object was not found.")
    if size == 0:
        raise EvidenceObjectValidationError("empty", "Evidence object is empty.")
    if size > settings.EVIDENCE_MAX_BYTES:
        raise EvidenceObjectValidationError(
            "too_large", "Evidence object exceeds the size limit."
        )

    try:
        response = _client().get_object(
            Bucket=settings.AWS_STORAGE_BUCKET_NAME,
            Key=object_key,
        )
        data = response["Body"].read(settings.EVIDENCE_MAX_BYTES)
    except (BotoCoreError, ClientError, OSError) as exc:
        raise StorageUnavailable from exc

    content_type = image_mime_from_bytes(data)
    if content_type not in settings.EVIDENCE_ALLOWED_MIME:
        raise EvidenceObjectValidationError(
            "invalid_image", "Evidence object is not a valid image."
        )
    return EvidenceValidationResult(size=size, content_type=content_type)

def presigned_get_url(object_key):
    try:
        return _public_client().generate_presigned_url(
            "get_object",
            Params={"Bucket": settings.AWS_STORAGE_BUCKET_NAME, "Key": object_key},
            ExpiresIn=settings.EVIDENCE_URL_TTL_SECONDS,
        )
    except (BotoCoreError, ClientError) as exc:
        raise StorageUnavailable from exc


def object_exists(object_key):
    try:
        _client().head_object(
            Bucket=settings.AWS_STORAGE_BUCKET_NAME,
            Key=object_key,
        )
    except ClientError as exc:
        status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        code = exc.response.get("Error", {}).get("Code")
        if status == 404 or code in {"404", "NoSuchKey", "NotFound"}:
            return False
        raise StorageUnavailable from exc
    except BotoCoreError as exc:
        raise StorageUnavailable from exc
    return True


def object_size(object_key):
    try:
        response = _client().head_object(
            Bucket=settings.AWS_STORAGE_BUCKET_NAME,
            Key=object_key,
        )
    except ClientError as exc:
        status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        code = exc.response.get("Error", {}).get("Code")
        if status == 404 or code in {"404", "NoSuchKey", "NotFound"}:
            return None
        raise StorageUnavailable from exc
    except BotoCoreError as exc:
        raise StorageUnavailable from exc

    return int(response["ContentLength"])
