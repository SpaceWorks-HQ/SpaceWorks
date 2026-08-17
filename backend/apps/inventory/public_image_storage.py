from dataclasses import dataclass
import logging
import time
import uuid

import boto3
from botocore.client import Config
from botocore.exceptions import BotoCoreError, ClientError
from django.conf import settings
from django.db import transaction
from rest_framework.exceptions import ValidationError

from apps.evidence.storage import StorageUnavailable
from apps.inventory.public_image_sniff import sniff_is_valid_image


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FinalizeResult:
    status: str
    size: int | None


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


def build_object_key(kind, makerspace_id, ext):
    if kind not in {"event", "items", "machine", "makerspace", "member", "printers"}:
        raise ValueError("Invalid public image kind.")
    return f"{kind}/{makerspace_id}/{uuid.uuid4().hex}{ext}"


def staging_key(final_key):
    return f"staging/{final_key}"


def is_safe_object_key(object_key):
    if object_key.startswith("/") or "\\" in object_key or ".." in object_key:
        return False
    return not any(ord(char) < 32 or ord(char) == 127 for char in object_key)


def delete_object(object_key):
    if not object_key:
        return True
    try:
        _client().delete_object(
            Bucket=settings.PUBLIC_IMAGE_BUCKET,
            Key=object_key,
        )
    except (BotoCoreError, ClientError):
        logger.exception("Failed to delete public image object %s.", object_key)
        return False
    return True


def release_public_image(makerspace, object_key, storage=None):
    """Delete a public image object and free its quota only if the delete succeeded.

    The HEAD must precede the delete -- the size is unobtainable once the object is gone
    -- but the quota must be released only once the delete reported success. Freeing on a
    silent failure is the direction that permanently grants free storage, which is why
    every step is best-effort and a failure frees nothing.

    `storage` overrides the module the two calls resolve against. `apps.bookings.storage`
    wraps this with its own implementations, and its service layer takes `storage` as an
    injected dependency, so binding these to this module unconditionally would quietly
    step around that seam.
    """
    from apps.makerspaces import limits

    sizer = storage.object_size if storage is not None else object_size
    deleter = storage.delete_object if storage is not None else delete_object

    size = None
    try:
        size = sizer(object_key)
    except Exception:
        logger.exception("Failed to size public image object before release: %s", object_key)
    try:
        deleted = deleter(object_key)
    except Exception:
        logger.exception("Failed to delete public image object during release: %s", object_key)
        return
    # Strict: only an affirmative True frees the quota. A deleter that reports nothing
    # cannot confirm anything, and treating silence as success is how a counter drifts
    # downward into permanently free storage.
    if not deleted or size is None:
        return
    try:
        limits.free_storage(makerspace, size)
    except Exception:
        logger.exception("Failed to free public image storage quota: %s", object_key)


def release_public_image_on_commit(makerspace, object_key, storage=None):
    """Schedule release_public_image for after the current transaction commits."""
    from apps.inventory.tenant_object_callbacks import release_public_image

    transaction.on_commit(lambda: release_public_image(makerspace, object_key, storage))


def delete_public_image_on_commit(makerspace, object_key):
    """Defer a public-image delete to after commit, without touching the quota."""
    from apps.inventory.tenant_object_callbacks import delete_public_image

    transaction.on_commit(lambda: delete_public_image(makerspace.pk, object_key))


def put_bytes(object_key, data, content_type):
    try:
        _client().put_object(
            Bucket=settings.PUBLIC_IMAGE_BUCKET,
            Key=object_key,
            Body=data,
            ContentType=content_type,
        )
    except (BotoCoreError, ClientError) as exc:
        raise StorageUnavailable from exc

def copy_object(source_key, dest_key):
    try:
        _client().copy_object(
            Bucket=settings.PUBLIC_IMAGE_BUCKET,
            CopySource={
                "Bucket": settings.PUBLIC_IMAGE_BUCKET,
                "Key": source_key,
            },
            Key=dest_key,
        )
    except (BotoCoreError, ClientError) as exc:
        raise StorageUnavailable from exc


def object_exists(object_key):
    try:
        _client().head_object(
            Bucket=settings.PUBLIC_IMAGE_BUCKET,
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
            Bucket=settings.PUBLIC_IMAGE_BUCKET,
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



def object_size_after_upload(object_key, attempts=10, delay_seconds=0.2):
    for attempt in range(attempts):
        size = object_size(object_key)
        if size is not None or attempt == attempts - 1:
            return size
        time.sleep(delay_seconds)
    return None


def _finalize_result(object_key, size):
    max_bytes = settings.PUBLIC_IMAGE_MAX_BYTES
    if size is None:
        result = FinalizeResult("missing", None)
    elif size == 0:
        result = FinalizeResult("empty", size)
    elif size > max_bytes:
        result = FinalizeResult("too_large", size)
    else:
        result = FinalizeResult("ok", size)

    if result.status != "ok":
        logger.warning(
            "Invalid public image upload: status=%s object_key=%s bucket=%s "
            "endpoint=%s storage_presign_method=%s max_bytes=%s observed_size=%s",
            result.status,
            object_key,
            settings.PUBLIC_IMAGE_BUCKET,
            settings.AWS_S3_ENDPOINT_URL,
            settings.STORAGE_PRESIGN_METHOD,
            max_bytes,
            result.size,
        )
    return result


def finalize_error_message(result):
    if result.status == "missing":
        return "Uploaded image was not found in storage."
    if result.status == "empty":
        return "Uploaded image is empty (0 bytes)."
    if result.status == "too_large":
        max_mb = settings.PUBLIC_IMAGE_MAX_BYTES // (1024 * 1024)
        return f"Uploaded image exceeds the {max_mb} MB limit."
    return ""


def public_image_key_in_use(
    makerspace_id, object_key, *, product_id=None, machine_id=None, event_id=None,
    profile_id=None, project_id=None, makerspace_field="",
):
    from django.db.models import Q
    from apps.events.models import Event
    from apps.inventory.models import InventoryProduct
    from apps.machines.models import Machine
    from apps.makerspaces.models import Makerspace, MemberProfile, MemberProject

    products = InventoryProduct.objects.filter(makerspace_id=makerspace_id, image_key=object_key)
    if product_id is not None:
        products = products.exclude(pk=product_id)
    if products.exists():
        return True
    machines = Machine.objects.filter(makerspace_id=makerspace_id, image_key=object_key)
    if machine_id is not None:
        machines = machines.exclude(pk=machine_id)
    if machines.exists():
        return True
    # Events share the bucket, so a key claimed by one must not be attachable to
    # another: clearing the first object's image deletes the underlying object and
    # would silently blank the second.
    events = Event.objects.filter(makerspace_id=makerspace_id, image_key=object_key)
    if event_id is not None:
        events = events.exclude(pk=event_id)
    if events.exists():
        return True
    # Member avatars and project images share the bucket too. Both are scoped through
    # the membership, since the profile carries no makerspace column of its own.
    profiles = MemberProfile.objects.filter(
        membership__makerspace_id=makerspace_id, avatar_key=object_key
    )
    if profile_id is not None:
        profiles = profiles.exclude(pk=profile_id)
    if profiles.exists():
        return True
    projects = MemberProject.objects.filter(
        profile__membership__makerspace_id=makerspace_id, image_key=object_key
    )
    if project_id is not None:
        projects = projects.exclude(pk=project_id)
    if projects.exists():
        return True
    makerspace_query = Makerspace.objects.filter(pk=makerspace_id)
    if makerspace_field == "logo_key":
        return makerspace_query.filter(cover_image_key=object_key).exists()
    if makerspace_field == "cover_image_key":
        return makerspace_query.filter(logo_key=object_key).exists()
    return makerspace_query.filter(Q(logo_key=object_key) | Q(cover_image_key=object_key)).exists()

def presigned_upload(object_key, content_type):
    try:
        if settings.STORAGE_PRESIGN_METHOD == "put":
            # Presigned PUT cannot enforce content-length at upload time; finalize HEADs staging.
            url = _public_client().generate_presigned_url(
                "put_object",
                Params={
                    "Bucket": settings.PUBLIC_IMAGE_BUCKET,
                    "Key": staging_key(object_key),
                    "ContentType": content_type,
                },
                ExpiresIn=settings.PUBLIC_IMAGE_URL_TTL_SECONDS,
            )
            return {
                "url": url,
                "method": "PUT",
                "headers": {"Content-Type": content_type},
            }
        return _public_client().generate_presigned_post(
            Bucket=settings.PUBLIC_IMAGE_BUCKET,
            Key=object_key,
            Fields={"Content-Type": content_type},
            Conditions=[
                {"Content-Type": content_type},
                ["content-length-range", 1, settings.PUBLIC_IMAGE_MAX_BYTES],
            ],
            ExpiresIn=settings.PUBLIC_IMAGE_URL_TTL_SECONDS,
        )
    except (BotoCoreError, ClientError) as exc:
        raise StorageUnavailable from exc


def finalize_upload(object_key):
    max_bytes = settings.PUBLIC_IMAGE_MAX_BYTES
    if settings.STORAGE_PRESIGN_METHOD != "put":
        return _finalize_result(object_key, object_size_after_upload(object_key))

    final_size = object_size(object_key)
    if final_size is not None:
        delete_object(staging_key(object_key))
        return _finalize_result(object_key, final_size)

    upload_staging_key = staging_key(object_key)
    size = object_size(upload_staging_key)
    if size is None:
        return _finalize_result(object_key, None)
    if not (1 <= size <= max_bytes):
        return _finalize_result(object_key, size)

    copy_object(upload_staging_key, object_key)
    delete_object(upload_staging_key)
    final_size = object_size(object_key)
    if final_size is None or not (1 <= final_size <= max_bytes):
        delete_object(object_key)
    return _finalize_result(object_key, final_size)


def public_url(object_key):
    if not object_key:
        return ""
    if settings.PUBLIC_IMAGE_BASE_URL:
        return f"{settings.PUBLIC_IMAGE_BASE_URL.rstrip('/')}/{object_key}"
    return (
        f"{settings.AWS_S3_PUBLIC_ENDPOINT_URL.rstrip('/')}/"
        f"{settings.PUBLIC_IMAGE_BUCKET}/{object_key}"
    )


def ext_for(content_type, filename):
    allowed_exts = settings.PUBLIC_IMAGE_ALLOWED_MIME.get(content_type)
    if not allowed_exts:
        raise ValidationError({"content_type": "Unsupported public image content type."})

    safe_name = (filename or "").replace("\\", "/").rsplit("/", 1)[-1]
    ext = f".{safe_name.rsplit('.', 1)[-1].lower()}" if "." in safe_name else ""
    if ext not in allowed_exts:
        raise ValidationError(
            {"filename": "Filename extension does not match the content type."}
        )
    return ext
