"""Revoking a membership, and declining or withdrawing a membership request.

Split out of `membership_services` (which re-exports both names) when that file reached the
300-line ceiling. Lock order is the one every membership service uses: makerspace, then the
membership or request row.
"""

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied

from apps.accounts import rbac
from apps.accounts.models import User
from apps.audit import services as audit
from apps.makerspaces.models import Makerspace, MakerspaceMembership, MembershipRequest


def revoke_membership(actor, membership, reason=""):
    with transaction.atomic():
        makerspace = Makerspace.objects.select_for_update().get(pk=membership.makerspace_id)
        membership = MakerspaceMembership.objects.select_for_update().get(pk=membership.pk)
        if not rbac.can(actor, rbac.Action.MANAGE_MEMBERS, makerspace.pk):
            raise PermissionDenied()
        if (not rbac.can(actor, rbac.Action.MANAGE_MAKERSPACE, makerspace.pk)
                and rbac.actions_for_membership(membership)):
            raise PermissionDenied("Managing staff memberships requires makerspace administration.")
        actor_is_superadmin = actor.is_superuser or actor.role == User.Role.SUPERADMIN
        if not actor_is_superadmin and rbac.Action.MANAGE_MAKERSPACE in rbac.actions_for_membership(membership):
            raise PermissionDenied("Only a superadmin can revoke a makerspace manager.")
        changed = membership.status != "revoked"
        if changed:
            membership.status = "revoked"
            membership.revoked_at = timezone.now()
            membership.revoked_by = actor
            membership.revocation_reason = reason or ""
        membership.can_refer = False
        membership.can_verify = False
        membership.save()
        if changed:
            audit.record(actor, "membership.revoked", makerspace=makerspace, target=membership,
                         meta={"reason": membership.revocation_reason})
            from apps.makerspaces.membership_payments import cancel_for_membership

            cancel_for_membership(membership, actor)
            # Everything else the membership carried that acts on its behalf goes with it:
            # the ID card (a live credential bearing their name and face) and any term with
            # its pending renewal charge.
            from apps.makerspaces.member_card_services import revoke_for_membership
            from apps.makerspaces.membership_plan_services import cancel_terms_for_membership

            revoke_for_membership(actor, membership)
            cancel_terms_for_membership(actor, membership)
        from apps.presence.services import end_sessions_for_membership
        end_sessions_for_membership(actor, membership)
        MembershipRequest.objects.filter(makerspace=makerspace, user=membership.user,
                                         state__in=["requested", "invited"]).update(
            state=MembershipRequest.State.REVOKED, decided_by=actor, decided_at=timezone.now()
        )
        return membership


def revoke_request(actor, request, reason=""):
    request = MembershipRequest.objects.select_related("makerspace").get(pk=request.pk)
    with transaction.atomic():
        makerspace = Makerspace.objects.select_for_update().get(pk=request.makerspace_id)
        request = MembershipRequest.objects.select_for_update().get(pk=request.pk)
        if not rbac.can(actor, rbac.Action.MANAGE_MEMBERS, makerspace.pk):
            raise PermissionDenied()
        if (request.assigned_role_id and request.assigned_role.granted_actions
                and not rbac.can(actor, rbac.Action.MANAGE_MAKERSPACE, makerspace.pk)):
            raise PermissionDenied("Managing staff invitations requires makerspace administration.")
        if request.state == MembershipRequest.State.ACTIVE and request.user_id:
            membership = MakerspaceMembership.objects.filter(makerspace=makerspace, user=request.user).first()
            if membership:
                return revoke_membership(actor, membership, reason)
        request.state = MembershipRequest.State.REVOKED
        request.decided_by = actor
        request.decided_at = timezone.now()
        request.decision_note = reason or request.decision_note
        request.save()
        audit.record(actor, "membership.revoked", makerspace=makerspace, target=request)
        return request
