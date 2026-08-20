"""Configured immutable audit anchor sink selection."""

from django.conf import settings

from .anchors_base import AnchorError
from .anchors_http import HttpCollectorAnchorSink
from .anchors_object_storage import ObjectStorageAnchorSink


def configured_sink():
    backend = str(getattr(settings, "AUDIT_ATTESTATION_ANCHOR_BACKEND", "")).lower()
    try:
        if backend == "object_storage":
            return ObjectStorageAnchorSink()
        if backend == "http":
            return HttpCollectorAnchorSink()
    except (TypeError, ValueError) as exc:
        raise AnchorError("The audit anchor settings are invalid.") from exc
    raise AnchorError("AUDIT_ATTESTATION_ANCHOR_BACKEND is not configured.")
