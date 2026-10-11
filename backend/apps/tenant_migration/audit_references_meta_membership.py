"""Audit meta references for membership plans, terms and invitation requests (phase 6).

Split from `audit_references_meta.py` to keep that file under the size ceiling; the
entries are merged into `AUDIT_META_REFERENCES` there.
"""

from .audit_references_targets import AuditReference, AuditReferenceDisposition

R = AuditReferenceDisposition.REMAP
S = AuditReferenceDisposition.SOURCE_LOCAL_SNAPSHOT

_TERM_ACTIONS = (
    "membership.term_created",
    "membership.term_cancelled",
    "membership.term_expired",
    "membership.renewal_raised",
)
_INVITATION_ACTIONS = (
    "invitation_request.submitted",
    "invitation_request.invited",
    "invitation_request.declined",
)


def _edges(model, pairs):
    return {edge: AuditReference(R, model) for edge in pairs}


MEMBERSHIP_AUDIT_EDGES = {
    ("staff.invitation_accepted", "membership_id"): AuditReference(R, "makerspaces.MakerspaceMembership"),
    ("staff.invitation_accepted", "role_id"): AuditReference(R, "makerspaces.MakerspaceRole"),
    ("staff.invitation_created", "role_id"): AuditReference(R, "makerspaces.MakerspaceRole"),
    ("membership.request_activated", "membership_id"): AuditReference(R, "makerspaces.MakerspaceMembership"),
    ("membership.vouched", "vouch_id"): AuditReference(S, "makerspaces.MembershipVouch"),
    ("membership.vouched", "voucher_id"): AuditReference(S, "accounts.User"),
    ("membership.vouchers_flagged", "voucher_ids"): AuditReference(S, "accounts.User"),
    ("membership.payment_after_expiry", "payment_id"): AuditReference(R, "payments.Payment"),
    **_edges(
        "makerspaces.MakerspaceMembership",
        tuple((action, "membership_id") for action in _TERM_ACTIONS),
    ),
    **_edges(
        "makerspaces.MembershipTerm",
        tuple((action, "term_id") for action in _TERM_ACTIONS),
    ),
    **_edges(
        "makerspaces.MembershipPlan",
        (
            ("membership.term_created", "plan_id"),
            ("membership_plan.created", "plan_id"),
            ("membership_plan.updated", "plan_id"),
        ),
    ),
    **_edges("payments.Payment", (("membership.renewal_raised", "payment_id"),)),
    **_edges(
        "makerspaces.InvitationRequest",
        tuple((action, "invitation_request_id") for action in _INVITATION_ACTIONS),
    ),
    **_edges(
        "makerspaces.MembershipRequest",
        (("invitation_request.invited", "membership_request_id"),),
    ),
    **_edges("makerspaces.MakerspaceRole", (("invitation_request.invited", "role_id"),)),
}
