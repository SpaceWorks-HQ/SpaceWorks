"""One mapping from a typed sink failure to a whole-log integrity failure.

The sinks decide transport vs configuration vs invalid evidence where the cause is still
known; this only translates. Invalid evidence (a conflict included) is an integrity
result and never retryable; only a transport failure carries the retryable cause.
"""

from apps.audit.anchors import AnchorInvalidEvidence, AnchorTransportError
from apps.audit.batch_verification import AuditFailureClass, AuditIntegrityFailure

ANCHOR_TRANSPORT = "anchor_transport"
VERIFICATION_UNAVAILABLE = "verification_unavailable"


def anchor_read_failure(exc, makerspace_id, batch_seq=None, *, detail=None):
    detail = detail or str(exc)
    if isinstance(exc, AnchorInvalidEvidence):
        return AuditIntegrityFailure(
            AuditFailureClass.ANCHOR_CONFLICT, detail, makerspace_id, batch_seq
        )
    cause = ANCHOR_TRANSPORT if isinstance(exc, AnchorTransportError) else VERIFICATION_UNAVAILABLE
    return AuditIntegrityFailure(
        AuditFailureClass.ANCHOR_UNAVAILABLE, detail, makerspace_id, batch_seq, cause=cause
    )
