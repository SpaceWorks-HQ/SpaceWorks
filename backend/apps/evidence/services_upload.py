"""Reusable evidence row creation + direct-to-staging presign.

Shared by the staff upload-URL endpoint and the phase 9b kiosk evidence route. The
presign targets the staging key (``presigned_upload`` binds it); the final object key is
never client-writable and a workflow promotes it exactly once. There is no backend blob
proxy: the browser uploads directly.
"""

import logging

from django.db import transaction

from apps.audit import services as audit
from apps.evidence.models import EvidencePhoto
from apps.evidence.storage import evidence_object_key, presigned_upload

logger = logging.getLogger(__name__)


def issue_upload(
    makerspace, *, actor, evidence_type, content_type, size_bytes=None,
    audit_action="evidence.upload_url_issued", audit_meta=None,
    consumption_state=EvidencePhoto.ConsumptionState.LEGACY_UNKNOWN,
):
    """Create the immutable EvidencePhoto row and return ``(photo, response data)``.

    Raises ``apps.evidence.storage.StorageUnavailable`` before any row is written when
    object storage cannot presign; callers map it to their 503 response.
    ``consumption_state`` stays ``legacy_unknown`` (never a cleanup candidate) unless the
    caller is a production presign view that opts its rows into abandoned-upload cleanup.
    """
    object_key = evidence_object_key(makerspace.pk, evidence_type)
    upload = presigned_upload(object_key, content_type)
    with transaction.atomic():
        photo = EvidencePhoto.objects.create(
            makerspace=makerspace,
            evidence_type=evidence_type,
            object_key=object_key,
            content_type=content_type,
            size_bytes=size_bytes,
            uploaded_by=actor,
            consumption_state=consumption_state,
        )
        meta = dict(audit_meta or {})
        if audit_meta is not None:
            meta["evidence_id"] = photo.pk
        audit.record(actor, audit_action, makerspace=makerspace, target=photo, meta=meta)
    logger.info(
        "evidence_upload_url_issued",
        extra={
            "evidence_id": photo.pk,
            "makerspace_id": makerspace.pk,
            "evidence_type": evidence_type,
        },
    )
    data = {
        "evidence_id": photo.pk,
        "upload_url": upload["url"],
        "fields": upload.get("fields", {}),
        "object_key": object_key,
    }
    if upload.get("method"):
        data["method"] = upload["method"]
        data["headers"] = upload.get("headers", {})
    return photo, data
