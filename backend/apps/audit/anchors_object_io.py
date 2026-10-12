"""Classified, budgeted S3 reads shared by the object anchor sink and its rotation mixin.

Listing is a manual ``list_objects_v2`` continuation loop rather than a boto paginator so
that every page request is visible to (and refused by) the per-attempt read budget.
"""

import json

from botocore.exceptions import (
    BotoCoreError,
    ClientError,
    NoCredentialsError,
    NoRegionError,
    ParamValidationError,
    PartialCredentialsError,
)

from .anchors_base import (
    MALFORMED_EVIDENCE_ERRORS,
    AnchorConfigurationError,
    AnchorConflict,
    AnchorInvalidEvidence,
    AnchorTransportError,
)
from .anchors_budget import consume

NOT_FOUND_CODES = frozenset({"404", "NoSuchKey", "NotFound"})
TRANSIENT_CODES = frozenset({
    "RequestTimeout", "RequestTimeTooSkewed", "SlowDown", "Throttling",
    "ThrottlingException", "RequestLimitExceeded", "ServiceUnavailable",
    "InternalError", "TooManyRequests",
})
CONFIGURATION_BOTO_ERRORS = (
    NoCredentialsError, PartialCredentialsError, NoRegionError, ParamValidationError,
)


def is_not_found(exc):
    status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
    code = exc.response.get("Error", {}).get("Code")
    # A missing BUCKET is also a 404, but it is a mis-configuration, not an absent anchor.
    return code in NOT_FOUND_CODES or (status == 404 and not code)


def classify_storage_error(exc, message):
    """The typed anchor error for a botocore/IO failure; never a plain AnchorError."""
    if isinstance(exc, ClientError):
        status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode") or 0
        code = str(exc.response.get("Error", {}).get("Code", ""))
        if code in TRANSIENT_CODES or status in {408, 429} or status >= 500:
            return AnchorTransportError(message)
        return AnchorConfigurationError(message)
    if isinstance(exc, CONFIGURATION_BOTO_ERRORS):
        return AnchorConfigurationError(message)
    # Endpoint/connection/read-timeout errors and socket-level OSErrors are transient.
    return AnchorTransportError(message)


def read_json_object(client, bucket, key, validate, budget):
    """Fetch and validate one object; ``None`` when it does not exist."""
    consume(budget)
    try:
        response = client.get_object(Bucket=bucket, Key=key)
        raw = response["Body"].read()
    except ClientError as exc:
        if is_not_found(exc):
            return None
        raise classify_storage_error(exc, "The object anchor could not be fetched.") from exc
    except (BotoCoreError, OSError) as exc:
        raise classify_storage_error(exc, "The object anchor could not be fetched.") from exc
    try:
        return validate(json.loads(raw.decode("utf-8")))
    except AnchorConflict:
        raise
    except MALFORMED_EVIDENCE_ERRORS as exc:
        raise AnchorInvalidEvidence("The object anchor is not valid evidence.") from exc


def iter_object_keys(client, bucket, prefix, budget, message):
    """Yield every key under ``prefix``, consuming one budget unit per page request."""
    token = None
    while True:
        params = {"Bucket": bucket, "Prefix": prefix}
        if token:
            params["ContinuationToken"] = token
        consume(budget)
        try:
            page = client.list_objects_v2(**params)
        except (BotoCoreError, ClientError, OSError) as exc:
            raise classify_storage_error(exc, message) from exc
        for item in page.get("Contents", []):
            yield item["Key"]
        token = page.get("NextContinuationToken") if page.get("IsTruncated") else None
        if not token:
            return
