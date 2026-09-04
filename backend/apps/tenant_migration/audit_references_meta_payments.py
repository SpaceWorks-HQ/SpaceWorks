"""Audit meta references for refunds and loan charges (forward plan phase 6).

Split from `audit_references_meta.py` to keep that file under the size ceiling; the
entries are merged into `AUDIT_META_REFERENCES` there. Every id here remaps: the
Payment, Refund and HardwareRequest rows all travel in a tenant archive.
"""

from .audit_references_targets import AuditReference, AuditReferenceDisposition

R = AuditReferenceDisposition.REMAP

_REFUND_ACTIONS = ("payment.refund_requested", "payment.refunded", "payment.refund_failed")
_LOAN_ACTIONS = ("loan.deposit_raised", "loan.late_fee_raised")


def _edges(model, pairs):
    return {edge: AuditReference(R, model) for edge in pairs}


PAYMENT_AUDIT_EDGES = {
    **_edges(
        "payments.Payment",
        [(action, "payment_id") for action in (*_REFUND_ACTIONS, *_LOAN_ACTIONS)],
    ),
    **_edges("payments.Refund", [(action, "refund_id") for action in _REFUND_ACTIONS]),
    **_edges(
        "hardware_requests.HardwareRequest",
        [(action, "request_id") for action in _LOAN_ACTIONS],
    ),
}
