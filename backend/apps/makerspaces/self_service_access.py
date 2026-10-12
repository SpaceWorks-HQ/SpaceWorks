"""Own-account access, scoped through the same tenant boundary as staff queries."""

from django.shortcuts import get_object_or_404
from rest_framework.exceptions import PermissionDenied

from apps.accounts import rbac
from apps.accounts.models import User
from apps.makerspaces.guards import require_feature, require_module
from apps.makerspaces.models import MakerspaceMembership


def own_membership(user, makerspace_id):
    if (not user.is_active or user.access_status != User.AccessStatus.ACTIVE
            or user.is_walk_in or user.is_tenant_dump_stub):
        raise PermissionDenied("An active member account is required.")
    rows = rbac.scope_by_makerspace(user, MakerspaceMembership.objects.all())
    membership = get_object_or_404(
        rows.select_related("makerspace", "assigned_role"),
        user=user, makerspace_id=makerspace_id, status="active",
    )
    require_module(membership.makerspace, "member_accounts")
    require_module(membership.makerspace, "membership")
    require_feature(membership.makerspace, "membership.self_service")
    return membership
