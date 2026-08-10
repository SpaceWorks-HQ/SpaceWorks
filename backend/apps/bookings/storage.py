'''Public-image storage helpers for bookable spaces.'''

import sys
import uuid
import time
import logging

from botocore.exceptions import BotoCoreError, ClientError
from django.conf import settings

from apps.bookings.models import BookableSpace
from apps.evidence.image_validation import image_mime_from_bytes
from apps.evidence.storage import StorageUnavailable
from apps.inventory import public_image_storage as shared

logger = logging.getLogger(__name__)

FinalizeResult = shared.FinalizeResult
is_safe_object_key = shared.is_safe_object_key
staging_key = shared.staging_key


def release_public_image_on_commit(makerspace, object_key):
    """Retire a space image, sizing and deleting through THIS module.

    A bare re-export of the shared function would resolve `object_size`/`delete_object`
    against the shared module, stepping around the `storage` dependency the service layer
    takes as a parameter -- so a caller that injected its own storage would silently get
    someone else's. `sys.modules[__name__]` is resolved per call, so a replaced attribute
    on this module is honoured.
    """
    shared.release_public_image_on_commit(
        makerspace, object_key, sys.modules[__name__]
    )


def _client():
    return shared._client()


def _public_client():
    return shared._public_client()


def copy_object(source_key, dest_key):
    try:
        _client().copy_object(
            Bucket=settings.PUBLIC_IMAGE_BUCKET,
            CopySource={
                'Bucket': settings.PUBLIC_IMAGE_BUCKET,
                'Key': source_key,
            },
            Key=dest_key,
        )
    except (BotoCoreError, ClientError) as exc:
        raise StorageUnavailable from exc


def delete_object(object_key):
    """Best-effort delete, reporting whether the object is actually gone.

    The boolean matters: `release_public_image` frees the storage quota only on a True,
    because freeing after a silent failure is the direction that permanently hands out
    free storage. Returning None on both success and failure made that unanswerable.
    """
    if not object_key:
        return True
    try:
        _client().delete_object(
            Bucket=settings.PUBLIC_IMAGE_BUCKET,
            Key=object_key,
        )
    except (BotoCoreError, ClientError):
        logger.exception('Failed to delete space image object %s.', object_key)
        return False
    return True


def ext_for(content_type, filename):
    return shared.ext_for(content_type, filename)


def finalize_error_message(result):
    return shared.finalize_error_message(result)


def object_exists(object_key):
    return object_size(object_key) is not None


def object_size(object_key):
    try:
        response = _client().head_object(
            Bucket=settings.PUBLIC_IMAGE_BUCKET,
            Key=object_key,
        )
    except ClientError as exc:
        status = exc.response.get('ResponseMetadata', {}).get('HTTPStatusCode')
        code = exc.response.get('Error', {}).get('Code')
        if status == 404 or code in {'404', 'NoSuchKey', 'NotFound'}:
            return None
        raise StorageUnavailable from exc
    except BotoCoreError as exc:
        raise StorageUnavailable from exc
    return int(response['ContentLength'])


def public_url(object_key):
    return shared.public_url(object_key)


def sniff_is_valid_image(object_key):
    try:
        response = _client().get_object(
            Bucket=settings.PUBLIC_IMAGE_BUCKET,
            Key=object_key,
        )
        data = response['Body'].read(settings.PUBLIC_IMAGE_MAX_BYTES)
    except ClientError as exc:
        status = exc.response.get('ResponseMetadata', {}).get('HTTPStatusCode')
        code = exc.response.get('Error', {}).get('Code')
        if status == 404 or code in {'404', 'NoSuchKey', 'NotFound'}:
            return False
        raise StorageUnavailable from exc
    except (BotoCoreError, OSError) as exc:
        raise StorageUnavailable from exc
    return bool(
        data
        and image_mime_from_bytes(data) in settings.PUBLIC_IMAGE_ALLOWED_MIME
    )


def build_object_key(makerspace_id, space_id, ext):
    return (
        f'spaces/{makerspace_id}/{space_id}/images/'
        f'{uuid.uuid4().hex}{ext}'
    )


def owned_prefix(space):
    return f'spaces/{space.makerspace_id}/{space.pk}/images/'


def is_owned_object_key(space, object_key):
    return bool(
        object_key
        and is_safe_object_key(object_key)
        and object_key.startswith(owned_prefix(space))
    )


def has_allowed_extension(object_key):
    extension = object_key.rsplit('.', 1)[-1].lower()
    suffix = f'.{extension}' if '.' in object_key else ''
    return any(
        suffix in extensions
        for extensions in settings.PUBLIC_IMAGE_ALLOWED_MIME.values()
    )


def public_image_key_in_use(makerspace_id, object_key):
    if BookableSpace.objects.filter(image_key=object_key).exists():
        return True
    return shared.public_image_key_in_use(makerspace_id, object_key)


def presigned_upload(object_key, content_type):
    try:
        if settings.STORAGE_PRESIGN_METHOD == 'put':
            url = _public_client().generate_presigned_url(
                'put_object',
                Params={
                    'Bucket': settings.PUBLIC_IMAGE_BUCKET,
                    'Key': staging_key(object_key),
                    'ContentType': content_type,
                },
                ExpiresIn=settings.PUBLIC_IMAGE_URL_TTL_SECONDS,
            )
            return {
                'url': url,
                'method': 'PUT',
                'headers': {'Content-Type': content_type},
            }
        return _public_client().generate_presigned_post(
            Bucket=settings.PUBLIC_IMAGE_BUCKET,
            Key=object_key,
            Fields={'Content-Type': content_type},
            Conditions=[
                {'Content-Type': content_type},
                ['content-length-range', 1, settings.PUBLIC_IMAGE_MAX_BYTES],
            ],
            ExpiresIn=settings.PUBLIC_IMAGE_URL_TTL_SECONDS,
        )
    except (BotoCoreError, ClientError) as exc:
        raise StorageUnavailable from exc


def _object_size_after_upload(object_key, attempts=10, delay_seconds=0.2):
    for attempt in range(attempts):
        size = object_size(object_key)
        if size is not None or attempt == attempts - 1:
            return size
        time.sleep(delay_seconds)
    return None


def finalize_upload(object_key):
    max_bytes = settings.PUBLIC_IMAGE_MAX_BYTES
    if settings.STORAGE_PRESIGN_METHOD != 'put':
        return shared._finalize_result(
            object_key,
            _object_size_after_upload(object_key),
        )
    final_size = object_size(object_key)
    if final_size is not None:
        delete_object(staging_key(object_key))
        return shared._finalize_result(object_key, final_size)
    upload_staging_key = staging_key(object_key)
    size = object_size(upload_staging_key)
    if size is None:
        return shared._finalize_result(object_key, None)
    if not 1 <= size <= max_bytes:
        return shared._finalize_result(object_key, size)
    copy_object(upload_staging_key, object_key)
    delete_object(upload_staging_key)
    final_size = object_size(object_key)
    if final_size is None or not 1 <= final_size <= max_bytes:
        delete_object(object_key)
    return shared._finalize_result(object_key, final_size)
