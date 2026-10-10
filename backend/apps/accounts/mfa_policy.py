"""The same MFA floor for browser, native, refresh, and Django sessions."""

from rest_framework.exceptions import AuthenticationFailed

from apps.accounts import rbac
from apps.accounts.models_mfa import UserMFA
from apps.makerspaces.models import Makerspace
from apps.makerspaces.platform import feature_enabled


def required(user):
    if user.is_superuser or user.role == "superadmin":
        return True
    # The common case (no tenant opted in) costs one scoped query, not one per action.
    candidates = Makerspace.objects.filter(enabled_features__contains=["security.staff_mfa_required"])
    local = rbac.scope_by_makerspace(user, candidates, "id")
    if any(rbac.effective_actions(user, space.pk) for space in local):
        return True
    if not rbac.has_any_org_authority(user):
        return False
    # Action-based scoping includes organization-derived staff, never community identity.
    for action in rbac.ROLE_GRANTABLE_ACTIONS:
        spaces = rbac.scope_by_action(user, action, candidates, "id")
        if any(feature_enabled(space, "security.staff_mfa_required") for space in spaces):
            return True
    return False


def credential(user):
    return UserMFA.objects.filter(user=user).first()


def needs_challenge(user):
    row = credential(user)
    return bool(row and row.enabled_at) or required(user)


def assert_verified(user, claims=None):
    row = credential(user)
    if row and claims is not None and str(claims.get("mfa_version") or "") != str(row.version):
        raise AuthenticationFailed("Sign in again and verify MFA.", code="mfa_required")
    if row and row.enabled_at:
        version = (claims or {}).get("mfa_version") if claims is not None else getattr(
            user, "_mfa_verified_version", None
        )
        if str(version or "") != str(row.version):
            raise AuthenticationFailed("Sign in again and verify MFA.", code="mfa_required")
    elif required(user):
        raise AuthenticationFailed("Enroll in MFA before continuing.", code="mfa_enrollment_required")


def stamp(user, row):
    user._mfa_verified_version = str(row.version)
