"""Stable explicit import surface for membership lifecycle services."""
from apps.makerspaces import role_services
from apps.audit import services as audit
from rest_framework.exceptions import ValidationError
from apps.makerspaces.membership_helpers import (
    MembershipOutcome, normalized_email, _eligible_user, _approvable_user,
    _is_community_invitation, _member_role, _outcome,
)
from apps.makerspaces.membership_legacy import invite_membership, refer_membership
from apps.makerspaces.membership_admission import request_membership, claim_invitation, approve_request
from apps.makerspaces.membership_revocation import revoke_membership, revoke_request
from apps.makerspaces.membership_verification import (
    set_can_refer, set_can_verify, unverify_member, verify_member,
)


def change_role(actor, membership, assigned_role):
    if membership.status != "active":
        raise ValidationError({"detail": "Only active memberships can change role."})
    changed = role_services.assign_role(makerspace=membership.makerspace, actor=actor,
                                        membership=membership, role=assigned_role)
    audit.record(actor, "membership.role_changed", makerspace=changed.makerspace, target=changed,
                 meta={"role_id": assigned_role.id})
    return changed
