from django.db import transaction

from apps.accounts import audit_events, rbac
from apps.accounts.models import User
from apps.accounts.models_social import SocialDelivery, SocialSurface
from apps.accounts.services_device_tokens import issue_device_token_pair
from apps.makerspaces.models import MakerspaceMembership
from apps.makerspaces.origin_scope import (
    AMBIGUOUS_STAFF_ORIGIN_SCOPE,
    NO_STAFF_ORIGIN_SCOPE,
    staff_origin_scope,
)
from apps.makerspaces.servability import servable_queryset


def assert_social_user_active(user):
    if not user.is_active or user.access_status != User.AccessStatus.ACTIVE:
        from apps.accounts.services_social_identity import SocialResolutionError

        raise SocialResolutionError("access_denied", 403)


def assert_staff_authority(user, request):
    from apps.accounts.services_social_identity import SocialResolutionError

    scope = getattr(request, "selected_makerspace_id", None) or staff_origin_scope(
        request
    )
    if scope is AMBIGUOUS_STAFF_ORIGIN_SCOPE:
        raise SocialResolutionError("staff_access_required", 403)
    if user.is_superuser or user.role == User.Role.SUPERADMIN:
        if scope is NO_STAFF_ORIGIN_SCOPE:
            return
    memberships = servable_queryset(
        MakerspaceMembership.objects.filter(user=user, status="active"),
        relation="makerspace",
    ).select_related("assigned_role")
    memberships = rbac.hide_from_superadmin(user, memberships, field="makerspace_id")
    if scope is not NO_STAFF_ORIGIN_SCOPE:
        memberships = memberships.filter(makerspace_id=scope)
    if any(rbac.actions_for_membership(row) for row in memberships):
        return
    raise SocialResolutionError("staff_access_required", 403)


def issue_social_session(user, *, surface, delivery, nonce_row, staff_scope=None):
    assert_social_user_active(user)
    from apps.backup.recovery import assert_token_issuance_allowed

    assert_token_issuance_allowed(user)
    if delivery == SocialDelivery.DEVICE:
        grant = nonce_row.device_grant
        with transaction.atomic():
            access, refresh, _family = issue_device_token_pair(user, grant)
        return {"access": access, "refresh": refresh, "device_grant": grant}
    from apps.accounts.tokens import SpaceWorksRefreshToken

    refresh = SpaceWorksRefreshToken.for_user(user)
    refresh["surface"] = surface
    if surface == SocialSurface.STAFF:
        refresh["staff_scope"] = staff_scope or "platform"
    return {"access": str(refresh.access_token), "refresh": str(refresh)}


def social_audit_meta(provider, outcome, subject):
    return {
        "provider": provider,
        "outcome": outcome,
        "subject_hash": audit_events.fingerprint(subject),
    }
