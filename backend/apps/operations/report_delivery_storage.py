"""Private-bucket storage for scheduled report files.

Reuses the evidence bucket client the same way member-card photos do: one private bucket,
keys namespaced per makerspace (`reports/<makerspace_id>/<report_key>/<uuid>.<fmt>`), and
reads only through short-lived signed URLs. Object keys are identifiers, not secrets.
"""

import uuid

from botocore.exceptions import BotoCoreError, ClientError
from django.conf import settings

from apps.evidence import storage
from apps.evidence.storage import StorageUnavailable
from apps.operations.report_exports import XLSX_CONTENT_TYPE

CONTENT_TYPES = {"csv": "text/csv", "xlsx": XLSX_CONTENT_TYPE}


def report_object_key(makerspace_id, report_key, fmt):
    return f"reports/{makerspace_id}/{report_key}/{uuid.uuid4().hex}.{fmt}"


def store_report_object(object_key, payload, fmt):
    try:
        storage._client().put_object(
            Bucket=settings.AWS_STORAGE_BUCKET_NAME,
            Key=object_key,
            Body=payload,
            ContentType=CONTENT_TYPES[fmt],
        )
    except (BotoCoreError, ClientError) as exc:
        raise StorageUnavailable from exc


def signed_download_url(object_key):
    try:
        return storage._public_client().generate_presigned_url(
            "get_object",
            Params={"Bucket": settings.AWS_STORAGE_BUCKET_NAME, "Key": object_key},
            ExpiresIn=settings.REPORT_DELIVERY_URL_TTL_SECONDS,
        )
    except (BotoCoreError, ClientError) as exc:
        raise StorageUnavailable from exc


def delete_report_object(object_key):
    """Best-effort: the evidence helper logs and swallows a failed delete."""
    storage.delete_object(object_key)
