"""Scheduled coordination for audit batch sealing and anchoring."""

import logging

from django.conf import settings
from django.db import connection

from apps.audit.anchors import configured_sink
from apps.audit.models import AuditMacKey


logger = logging.getLogger(__name__)


def is_writable_primary():
    if connection.vendor != "postgresql":
        return False
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT NOT pg_is_in_recovery(), "
            "current_setting('transaction_read_only') = 'off'"
        )
        primary, writable = cursor.fetchone()
    return bool(primary and writable)


def run_audit_attestation():
    # Blank by default: a dormant installation must not fail every scheduled cycle.
    if not getattr(settings, "AUDIT_ATTESTATION_ANCHOR_BACKEND", ""):
        return None
    if not is_writable_primary():
        logger.info("audit_attestation_skipped_non_writable_primary")
        return {"sealed": 0, "failed": 0, "skipped": "non_writable_primary"}
    try:
        sink = configured_sink()
    except Exception:  # noqa: BLE001 - scheduled retry handles provider recovery
        logger.exception("audit_attestation_sink_unavailable")
        return {"sealed": 0, "failed": 1}
    from apps.audit.batches import (
        activate_scope,
        batch_envelope,
        seal_scope,
        synchronize_anchors,
    )

    scope_ids = list(
        AuditMacKey.objects.order_by("makerspace_id").values_list(
            "makerspace_id", flat=True
        )
    )
    result = {"sealed": 0, "failed": 0}
    for makerspace_id in scope_ids:
        try:
            key = activate_scope(makerspace_id, sink)
            synchronize_anchors(makerspace_id, sink, key)
            batch = seal_scope(makerspace_id, key)
            if batch is not None:
                sink.publish(batch_envelope(batch))
                result["sealed"] += 1
        except Exception:  # noqa: BLE001 - one failed scope must not stop others
            result["failed"] += 1
            logger.exception(
                "audit_attestation_scope_failed",
                extra={"makerspace_id": makerspace_id},
            )
    return result
