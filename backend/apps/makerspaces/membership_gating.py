"""Which membership REQUESTS the `membership` module gates (plan A7, end to end).

`invite_membership` already discriminates on the assigned role: an invitation whose role
grants actions is a STAFF invitation and works with the module off, because
`MakerspaceMembership` is core RBAC state. That rule used to stop at the invitation. The
claim, the queue, the approval and the decline all either gated everything (so a staff
invitation issued with the module off could never be approved, declined or even listed) or
gated nothing (so a community invitation or a referral issued while the module was on stayed
claimable after it was switched off, activating a community member through a surface the
operator had removed). Every step now asks the same question, here.
"""

from django.db.models import Q

from apps.makerspaces.guards import require_module
from apps.makerspaces.models import MembershipRequest


def grants_actions(role):
    return bool(role is not None and role.granted_actions)


def is_staff_invitation(request):
    """A staff invitation: an INVITE whose role grants actions and that is not a referral."""
    return (
        request.kind == MembershipRequest.Kind.INVITE
        and not request.auto_activate_on_claim
        and grants_actions(request.assigned_role)
    )


def staff_invitation_q(prefix=""):
    """The queryset twin of `is_staff_invitation`, for the module-off queue."""
    return Q(**{
        f"{prefix}kind": MembershipRequest.Kind.INVITE,
        f"{prefix}auto_activate_on_claim": False,
        f"{prefix}assigned_role__isnull": False,
    }) & ~Q(**{f"{prefix}assigned_role__granted_actions": []})


def require_module_for_request(makerspace, request, *, outcome_role=None):
    """Gate a decision on `request` unless it is staff business end to end.

    `outcome_role` is the role an approval would assign: approving a staff invitation
    with a role that grants nothing would mint a community member, so it is gated too.
    """
    staff = is_staff_invitation(request) and (
        outcome_role is None or grants_actions(outcome_role)
    )
    if not staff:
        require_module(makerspace, "membership")
