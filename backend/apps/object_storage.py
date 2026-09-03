"""Shared deletion primitives for versioned S3-compatible object stores."""

import logging

from botocore.exceptions import BotoCoreError, ClientError


logger = logging.getLogger(__name__)

UNSUPPORTED_LIST_OBJECT_VERSIONS_ERROR_CODES = frozenset(
    {
        "InvalidRequest",
        "MethodNotAllowed",
        "NotImplemented",
        "UnsupportedOperation",
        "XNotImplemented",
    }
)


def delete_all_versions(client, *, bucket, key, require_version_listing=False):
    """Delete every retained version and delete marker for one exact key.

    Some S3-compatible providers do not implement ``ListObjectVersions``. In that
    case a normal delete remains the only available operation, so callers stay
    runnable instead of turning a tenant purge into a permanent failure.
    """
    params = {"Bucket": bucket, "Prefix": key}
    try:
        first_page = client.list_object_versions(**params)
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code")
        if (
            code in UNSUPPORTED_LIST_OBJECT_VERSIONS_ERROR_CODES
            and not require_version_listing
        ):
            logger.warning(
                "object_version_listing_failed_falling_back",
                extra={"bucket": bucket, "object_key": key, "error_code": code},
                exc_info=True,
            )
            client.delete_object(Bucket=bucket, Key=key)
            return
        _log_listing_failure(bucket=bucket, key=key)
        raise
    except BotoCoreError:
        _log_listing_failure(bucket=bucket, key=key)
        raise

    try:
        objects = _listed_versions(
            client, bucket=bucket, key=key, first_page=first_page
        )
    except (BotoCoreError, ClientError):
        _log_listing_failure(bucket=bucket, key=key)
        raise

    if not objects:
        client.delete_object(Bucket=bucket, Key=key)
        return

    for start in range(0, len(objects), 1000):
        response = client.delete_objects(
            Bucket=bucket,
            Delete={"Objects": objects[start : start + 1000], "Quiet": True},
        )
        errors = (response or {}).get("Errors", ())
        if errors:
            first = errors[0]
            raise ClientError(
                {
                    "Error": {
                        "Code": first.get("Code", "DeleteObjectsError"),
                        "Message": first.get("Message", "Object version deletion failed."),
                    }
                },
                "DeleteObjects",
            )


def _listed_versions(client, *, bucket, key, first_page):
    objects = []
    page = first_page
    while True:
        objects.extend(
            {"Key": item["Key"], "VersionId": item["VersionId"]}
            for group in (page.get("Versions", ()), page.get("DeleteMarkers", ()))
            for item in group
            if item.get("Key") == key
        )
        if not page.get("IsTruncated"):
            return objects
        params = {
            "Bucket": bucket,
            "Prefix": key,
            "KeyMarker": page.get("NextKeyMarker"),
            "VersionIdMarker": page.get("NextVersionIdMarker"),
        }
        page = client.list_object_versions(
            **{name: value for name, value in params.items() if value is not None}
        )


def _log_listing_failure(*, bucket, key):
    logger.error(
        "object_version_listing_failed_propagating",
        extra={"bucket": bucket, "object_key": key},
        exc_info=True,
    )
