"""Whole-log verification phase coordinator."""

from apps.audit.anchors import AnchorError, configured_sink
from apps.audit.batch_verification import AuditFailureClass, AuditIntegrityFailure
from apps.audit.models import AuditSigningKey

from .integrity_activation import _verify_activation, _verify_scope_registry
from .integrity_batches import _verify_batches
from .integrity_rows import _verify_rows


def verify_audit_integrity(*, sink=None):
    """Return the first failure across rows, local chains, signatures, and anchors."""
    failure = _verify_rows()
    if failure:
        return failure
    try:
        sink = sink or configured_sink()
    except AnchorError as exc:
        return AuditIntegrityFailure(AuditFailureClass.ANCHOR_UNAVAILABLE, str(exc))
    failure = _verify_scope_registry()
    if failure:
        return failure
    for key in AuditSigningKey.objects.order_by("makerspace_id"):
        failure = _verify_activation(key, sink) or _verify_batches(key, sink)
        if failure:
            return failure
    return None
