"""Whole-log verification phase coordinator."""

from apps.audit.anchors import AnchorError, configured_sink
from apps.audit.batch_verification import AuditFailureClass, AuditIntegrityFailure
from apps.audit.models import AuditSigningKey

from .integrity_activation import _verify_activation, _verify_scope_registry
from .integrity_batches import _verify_batches
from .integrity_rotations import _verify_rotation_chain
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
    scope_ids = AuditSigningKey.objects.order_by("makerspace_id").values_list(
        "makerspace_id", flat=True
    ).distinct()
    for makerspace_id in scope_ids:
        keys = list(
            AuditSigningKey.objects.filter(makerspace_id=makerspace_id)
            .exclude(rotation_to__events__state="ABORTED")
            .order_by("version")
        )
        # Genesis is verified once; rotations extend it, and batches are traversed once
        # with the signer selected from the interval that authorizes that sequence.
        failure = (
            _verify_activation(keys[0], sink)
            or _verify_rotation_chain(keys, sink)
            or _verify_batches(makerspace_id, sink)
        )
        if failure:
            return failure
    return None
