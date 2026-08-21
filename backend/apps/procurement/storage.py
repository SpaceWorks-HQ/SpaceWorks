from dataclasses import dataclass
import logging
import uuid

import boto3
from botocore.client import Config
from botocore.exceptions import BotoCoreError, ClientError
from django.conf import settings
from rest_framework.exceptions import ValidationError

from apps.evidence.image_validation import image_mime_from_bytes
from apps.evidence.storage import StorageUnavailable
from apps.object_storage import delete_all_versions


logger = logging.getLogger(__name__)
PDF_CONTENT_TYPE = "application/pdf"
ALLOWED_EXTENSIONS_BY_MIME = {
    PDF_CONTENT_TYPE: {"pdf"},
    "image/jpeg": {"jpg", "jpeg"},
    "image/png": {"png"},
    "image/webp": {"webp"},
}


@dataclass(frozen=True)
class ReceiptObjectValidationResult:
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


def receipt_object_key(makerspace_id, ext):
    safe_ext = str(ext).lower().lstrip(".")
    return f"procurement/{makerspace_id}/{uuid.uuid4().hex}.{safe_ext}"


def staging_key(final_key):
    return f"staging/{final_key}"


def assert_receipt_object_key_for_makerspace(object_key, makerspace_id):
    if not str(object_key).startswith(f"procurement/{makerspace_id}/"):
        raise ValidationError(
            {"object_key": "Receipt key does not belong to this makerspace."}
        )


def assert_receipt_object_key_for_item(item, object_key):
    from apps.procurement.models import ToBuyReceipt

    assert_receipt_object_key_for_makerspace(object_key, item.makerspace_id)
    if ToBuyReceipt.objects.filter(object_key=object_key).exists():
        raise ValidationError({"object_key": "This receipt is already attached."})


def ext_for(content_type, filename):
    allowed_mime = set(settings.PROCUREMENT_RECEIPT_ALLOWED_MIME)
    allowed_exts = ALLOWED_EXTENSIONS_BY_MIME.get(content_type)
    if content_type not in allowed_mime or not allowed_exts:
        raise ValidationError({"content_type": "Unsupported receipt document type."})

    safe_name = (filename or "").replace("\\", "/").rsplit("/", 1)[-1]
    ext = safe_name.rsplit(".", 1)[-1].lower() if "." in safe_name else ""
    if ext not in allowed_exts:
        raise ValidationError(
            {"filename": "Filename extension does not match the content type."}
        )
    return ext


def presigned_upload(object_key, content_type):
    try:
        if settings.STORAGE_PRESIGN_METHOD == "put":
            url = _public_client().generate_presigned_url(
                "put_object",
                Params={
                    "Bucket": settings.AWS_STORAGE_BUCKET_NAME,
                    "Key": staging_key(object_key),
                    "ContentType": content_type,
                },
                ExpiresIn=settings.EVIDENCE_URL_TTL_SECONDS,
            )
            return {"url": url, "method": "PUT", "headers": {"Content-Type": content_type}}
        return _public_client().generate_presigned_post(
            Bucket=settings.AWS_STORAGE_BUCKET_NAME,
            Key=object_key,
            Fields={"Content-Type": content_type},
            Conditions=[
                {"Content-Type": content_type},
                ["content-length-range", 1, settings.PROCUREMENT_RECEIPT_MAX_BYTES],
            ],
            ExpiresIn=settings.EVIDENCE_URL_TTL_SECONDS,
        )
    except (BotoCoreError, ClientError) as exc:
        raise StorageUnavailable from exc


def delete_object(object_key):
    try:
        delete_all_versions(
            _client(), bucket=settings.AWS_STORAGE_BUCKET_NAME, key=object_key
        )
    except (BotoCoreError, ClientError):
        logger.exception("Failed to delete procurement receipt %s.", object_key)


def copy_object(source_key, dest_key):
    try:
        _client().copy_object(
            Bucket=settings.AWS_STORAGE_BUCKET_NAME,
            CopySource={"Bucket": settings.AWS_STORAGE_BUCKET_NAME, "Key": source_key},
            Key=dest_key,
        )
    except (BotoCoreError, ClientError) as exc:
        raise StorageUnavailable from exc


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


def finalize_upload(object_key, max_bytes):
    if settings.STORAGE_PRESIGN_METHOD != "put":
        return object_size(object_key)

    final_size = object_size(object_key)
    if final_size is not None:
        delete_object(staging_key(object_key))
        return final_size

    upload_staging_key = staging_key(object_key)
    size = object_size(upload_staging_key)
    if size is None:
        return None
    if not (1 <= size <= max_bytes):
        return size

    copy_object(upload_staging_key, object_key)
    delete_object(upload_staging_key)
    final_size = object_size(object_key)
    if final_size is None or not (1 <= final_size <= max_bytes):
        delete_object(object_key)
    return final_size


def finalize_receipt_upload(item, object_key):
    assert_receipt_object_key_for_item(item, object_key)
    finalize_upload(object_key, settings.PROCUREMENT_RECEIPT_MAX_BYTES)
    return validate_receipt_object(object_key)


def presigned_get_url(object_key):
    try:
        return _public_client().generate_presigned_url(
            "get_object",
            Params={"Bucket": settings.AWS_STORAGE_BUCKET_NAME, "Key": object_key},
            ExpiresIn=settings.EVIDENCE_URL_TTL_SECONDS,
        )
    except (BotoCoreError, ClientError) as exc:
        raise StorageUnavailable from exc


def validate_receipt_object(object_key):
    size = object_size(object_key)
    if size is None:
        raise ValidationError({"object_key": "Receipt document was not found."})
    if size == 0:
        raise ValidationError({"object_key": "Receipt document is empty."})
    if size > settings.PROCUREMENT_RECEIPT_MAX_BYTES:
        raise ValidationError({"object_key": "Receipt document exceeds the size limit."})

    try:
        response = _client().get_object(
            Bucket=settings.AWS_STORAGE_BUCKET_NAME,
            Key=object_key,
        )
        data = response["Body"].read(settings.PROCUREMENT_RECEIPT_MAX_BYTES)
    except (BotoCoreError, ClientError, OSError) as exc:
        raise StorageUnavailable from exc

    content_type = PDF_CONTENT_TYPE if data.startswith(b"%PDF-") else None
    if content_type is None:
        image_type = image_mime_from_bytes(data)
        if image_type and image_type.startswith("image/"):
            content_type = image_type
    if content_type not in set(settings.PROCUREMENT_RECEIPT_ALLOWED_MIME):
        raise ValidationError(
            {"object_key": "Receipt document is not a valid PDF or image."},
            code="invalid_document",
        )
    return ReceiptObjectValidationResult(size=size, content_type=content_type)
