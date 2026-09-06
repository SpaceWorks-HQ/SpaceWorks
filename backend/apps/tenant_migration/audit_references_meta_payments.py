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


#: Settlement receipts are audited too, and their primary keys are semantic references
#: like any other: left undeclared they would survive a Lane D import as stale SOURCE
#: ids inside immutable audit metadata, pointing at whatever row happened to take that
#: number on the target.
_SETTLEMENT_ACTIONS = ("payment.paid_offline", "payment.settlement_amended")


PAYMENT_AUDIT_EDGES = {
    **_edges(
        "payments.ManualSettlement",
        [(action, "settlement_id") for action in _SETTLEMENT_ACTIONS],
    ),
    **_edges(
        "payments.ManualSettlement",
        [("payment.settlement_amended", "amends_id")],
    ),
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
