"""Voluntary departure and stopping future renewal, without changing a plan."""

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied

from apps.accounts import rbac
from apps.audit import services as audit
from apps.makerspaces.guards import require_feature_locked, require_module
from apps.makerspaces.models import MakerspaceMembership, MembershipTerm
from apps.makerspaces.self_service_access import own_membership


def _locked_membership(actor, makerspace_id):
    makerspace = require_feature_locked(makerspace_id, "membership.self_service")
    require_module(makerspace, "membership")
    require_module(makerspace, "member_accounts")
    own_membership(actor, makerspace_id)
    membership = rbac.scope_by_makerspace(actor, MakerspaceMembership.objects.all()).select_for_update().get(
        makerspace_id=makerspace_id, user=actor, status="active",
    )
    return makerspace, membership


@transaction.atomic
def cancel_renewal(actor, makerspace_id, reason):
    makerspace, membership = _locked_membership(actor, makerspace_id)
    if membership.renewal_cancelled_at is None:
        membership.renewal_cancelled_at = timezone.now()
        membership.save(update_fields=["renewal_cancelled_at"])
        # The member keeps the current term, but no pending next-term renewal
        # debt should remain collectible after an explicit do-not-renew request.
        from apps.makerspaces.membership_plan_services import _cancel_pending_renewal
        terms = rbac.scope_by_makerspace(
            actor, MembershipTerm.objects.filter(membership=membership, renewal_payment__isnull=False),
            makerspace_field="membership__makerspace_id",
        )
        for term in terms:
            _cancel_pending_renewal(makerspace, term, actor)
        audit.record(actor, "membership.renewal_cancelled", makerspace=makerspace,
                     target=membership, meta={"reason": reason})
        from apps.makerspaces.membership_renewal_notifications import notify_membership
        transaction.on_commit(lambda: notify_membership(membership, "cancelled"))
    return membership


@transaction.atomic
def leave_makerspace(actor, makerspace_id, reason):
    makerspace, membership = _locked_membership(actor, makerspace_id)
    if rbac.Action.MANAGE_MAKERSPACE in rbac.actions_for_membership(membership):
        others = rbac.scope_by_makerspace(actor, MakerspaceMembership.objects.filter(
            makerspace=makerspace, status="active", user__is_active=True,
            user__access_status="active", user__is_tenant_dump_stub=False,
        )).exclude(pk=membership.pk)
        if not any(rbac.Action.MANAGE_MAKERSPACE in rbac.actions_for_membership(row) for row in others):
            raise PermissionDenied("Assign another makerspace manager before leaving.")
    membership.renewal_cancelled_at = membership.renewal_cancelled_at or timezone.now()
    from apps.makerspaces.membership_revocation import _revoke_locked
    return _revoke_locked(actor, membership, makerspace, reason, self_leave=True)
