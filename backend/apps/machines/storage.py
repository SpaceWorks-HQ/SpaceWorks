"""Private-bucket storage for machine manuals/SOP documents.

Mirrors apps/warranty/storage.py: same PRIVATE evidence bucket, presign POST/PUT per
STORAGE_PRESIGN_METHOD, TOCTOU-safe finalize, and byte-sniff validation (%PDF- for PDFs,
image magic for images) — stronger than trusting the declared content type.
"""
from dataclasses import dataclass
import logging
import uuid

import boto3
from botocore.client import Config
from botocore.exceptions import BotoCoreError, ClientError
from django.conf import settings
from rest_framework.exceptions import ValidationError

from apps.evidence.storage import StorageUnavailable
from apps.maker_file_formats import (
    ALLOWED_EXTENSIONS_BY_MIME,
    STRICT_MIME_BY_EXTENSION,
    allowed_pair,
    extension_from_name,
    has_required_signature,
    sniff_pdf_or_image,
)
from apps.object_storage import delete_all_versions

logger = logging.getLogger(__name__)
PDF_CONTENT_TYPE = "application/pdf"


@dataclass(frozen=True)
class MachineObjectValidationResult:
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


def machine_object_key(makerspace_id, ext):
    safe_ext = str(ext).lower().lstrip(".")
    return f"machines/{makerspace_id}/{uuid.uuid4().hex}.{safe_ext}"


def staging_key(final_key):
    return f"staging/{final_key}"


def assert_machine_object_key_for_makerspace(object_key, makerspace_id):
    if not str(object_key).startswith(f"machines/{makerspace_id}/"):
        raise ValidationError(
            {"object_key": "Machine document key does not belong to this makerspace."}
        )


def ext_for(content_type, filename):
    ext = extension_from_name(filename)
    if not allowed_pair(
        ext,
        content_type,
        settings.MACHINE_DOC_ALLOWED_EXT,
        settings.MACHINE_DOC_ALLOWED_MIME,
    ):
        raise ValidationError({"filename": "Unsupported document extension or content type."})
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
                ["content-length-range", 1, settings.MACHINE_DOC_MAX_BYTES],
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
        logger.exception("Failed to delete machine document %s.", object_key)


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


def presigned_get_url(object_key):
    try:
        return _public_client().generate_presigned_url(
            "get_object",
            Params={"Bucket": settings.AWS_STORAGE_BUCKET_NAME, "Key": object_key},
            ExpiresIn=settings.EVIDENCE_URL_TTL_SECONDS,
        )
    except (BotoCoreError, ClientError) as exc:
        raise StorageUnavailable from exc


def validate_machine_object(object_key):
    size = object_size(object_key)
    if size is None:
        raise ValidationError({"object_key": "Machine document was not found."})
    if size == 0:
        raise ValidationError({"object_key": "Machine document is empty."})
    if size > settings.MACHINE_DOC_MAX_BYTES:
        raise ValidationError({"object_key": "Machine document exceeds the size limit."})

    try:
        response = _client().get_object(
            Bucket=settings.AWS_STORAGE_BUCKET_NAME,
            Key=object_key,
        )
        data = response["Body"].read(settings.MACHINE_DOC_MAX_BYTES)
        stored_content_type = str(response.get("ContentType", "")).lower()
    except (BotoCoreError, ClientError, OSError) as exc:
        raise StorageUnavailable from exc

    ext = extension_from_name(object_key)
    if not allowed_pair(
        ext,
        stored_content_type,
        settings.MACHINE_DOC_ALLOWED_EXT,
        settings.MACHINE_DOC_ALLOWED_MIME,
    ):
        raise ValidationError(
            {"object_key": "Machine document extension and content type do not match."},
            code="invalid_document",
        )

    sniffed = sniff_pdf_or_image(data)
    strict_mime = STRICT_MIME_BY_EXTENSION.get(ext)
    if strict_mime or sniffed:
        if not strict_mime or stored_content_type != strict_mime or sniffed != strict_mime:
            raise ValidationError(
                {"object_key": "Machine document content does not match its extension."},
                code="invalid_document",
            )
        content_type = sniffed
    else:
        if not has_required_signature(ext, data):
            raise ValidationError(
                {"object_key": "Machine document signature is invalid."},
                code="invalid_document",
            )
        content_type = stored_content_type
    return MachineObjectValidationResult(size=size, content_type=content_type)
