"""Post-purge private and public object deletion."""

import logging

from django.conf import settings


logger = logging.getLogger(__name__)


def _delete_storage_keys(storage_keys):
    if not storage_keys:
        return

    from apps.evidence import storage

    try:
        client = storage._client()
    except Exception:
        logger.exception("Failed to create storage client for makerspace purge keys: %s", storage_keys)
        return

    for key in storage_keys:
        try:
            client.delete_object(Bucket=settings.AWS_STORAGE_BUCKET_NAME, Key=key)
        except Exception:
            logger.exception("Failed to delete makerspace purge storage key: %s", key)


def _delete_public_image_keys(storage_keys):
    if not storage_keys:
        return

    from apps.inventory import public_image_storage

    for key in storage_keys:
        public_image_storage.delete_object(key)
