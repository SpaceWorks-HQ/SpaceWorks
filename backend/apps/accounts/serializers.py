from rest_framework import serializers
from rest_framework.exceptions import AuthenticationFailed, PermissionDenied
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer, TokenRefreshSerializer
from rest_framework_simplejwt.settings import api_settings

from apps.accounts.models import User
from apps.accounts.services_refresh_tokens import rotate_refresh_token
from apps.accounts.tokens import SpaceWorksRefreshToken, validate_auth_generation
from apps.accounts.models_social import SocialSurface


VERIFICATION_ONLY_SURFACE = "verification_only"


def user_payload(user, request=None):
    from apps.accounts import rbac
    from apps.makerspaces.origin_scope import origin_scoped_makerspace_id

    memberships = user.makerspace_memberships.select_related("makerspace", "assigned_role")
    claim_context = getattr(user, "_claim_audit_context", None)
    if claim_context is not None:
        memberships = memberships.filter(pk=claim_context.membership_id)
    archived_ids = rbac.archived_makerspace_ids()
    if archived_ids:
        memberships = memberships.exclude(makerspace_id__in=archived_ids)
    memberships = rbac.hide_from_superadmin(user, memberships, field="makerspace_id")
    if request is not None and getattr(request, 'device_grant', None):
        memberships = memberships.filter(status='active')
    elif request is not None:
        scoped_makerspace_id = origin_scoped_makerspace_id(request)
        if scoped_makerspace_id is not None:
            memberships = memberships.filter(makerspace_id=scoped_makerspace_id)

    # Resolve effective actions from the already select_related-loaded membership rows so
    # /auth/login and /auth/me stay O(1) queries — calling rbac.effective_actions() per row
    # would re-query the membership + archived set for each makerspace (1+2N). This mirrors
    # rbac.effective_actions: a superadmin in a VISIBLE makerspace gets the full grantable
    # set; a superadmin who is an explicit member of a hard-hidden makerspace (kept here by
    # hide_from_superadmin's explicit-member carve-out) is membership-limited; everyone else
    # uses the membership's resolved actions. Archived rows are already excluded above.
    is_superadmin = user.is_superuser or user.role == User.Role.SUPERADMIN
    hidden_ids = rbac.superadmin_hidden_makerspace_ids() if is_superadmin else ()

    def _membership_actions(m):
        if is_superadmin and not rbac._id_in(m.makerspace_id, hidden_ids):
            return sorted(rbac.ROLE_GRANTABLE_ACTIONS)
        return sorted(rbac.actions_for_membership(m))

    def _can_configure_machine_types(m):
        if is_superadmin and not rbac._id_in(m.makerspace_id, hidden_ids):
            return True
        if m.assigned_role_id is not None:
            return bool(
                m.assigned_role
                and m.assigned_role.makerspace_id == m.makerspace_id
                and m.assigned_role.legacy_role == "space_manager"
            )
        return m.role == "space_manager"

    # Resolved in ONE batch (two link queries total) rather than per membership: the
    # per-actor `role_scope.manage_scope_for` would put an N+1 behind /auth/me and
    # /auth/login, which is the query budget the block above exists to protect.
    from apps.machines import role_scope

    memberships = list(memberships)
    machine_scopes = role_scope.manage_scopes_for_memberships(memberships)

    def _is_machine_only(m):
        """The console's copy of `role_scope.is_machine_only`, batched.

        Kept in step with that function deliberately: it decides whether the Notifications
        tab and its unread badge render, and the backend refuses the inbox for exactly this
        actor. A tab that renders and then 403s on every request is worse than no tab.
        """
        if is_superadmin and not rbac._id_in(m.makerspace_id, hidden_ids):
            return False
        actions = set(_membership_actions(m))
        if rbac.Action.MANAGE_MACHINES not in actions:
            return False
        if machine_scopes.get(m.pk, role_scope.NOTHING) is role_scope.EXEMPT:
            return False
        # STORED, not effective: `actions` is the expanded set, in which MANAGE_MACHINES
        # always implies MANAGE_PRINTING -- testing it there would make this always False.
        # Read off the role row, matching `role_scope.is_machine_only`'s printing arm.
        if _stores_printing(m):
            return False
        return not (
            rbac.Action.VIEW_INVENTORY in actions
            or rbac.Action.MANAGE_MAKERSPACE in actions
        )

    def _stores_printing(m):
        if m.assigned_role_id is None:
            return rbac.Action.MANAGE_PRINTING in rbac._MEMBERSHIP_ROLE_ACTIONS.get(
                m.role, ()
            )
        role = m.assigned_role
        if role is None or role.makerspace_id != m.makerspace_id:
            return False
        granted = role.granted_actions if isinstance(role.granted_actions, list) else []
        return rbac.Action.MANAGE_PRINTING in granted

    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "display_name": user.display_name,
        "phone": user.phone,
        "email_verified": user.email_verified_at is not None,
        "role": user.role,
        "is_superuser": user.is_superuser,
        "must_change_password": user.must_change_password,
        "makerspaces": [
            {
                "id": m.makerspace_id,
                "slug": m.makerspace.slug,
                "role": m.role,
                "role_id": m.assigned_role_id,
                "role_name": (
                    m.assigned_role.name
                    if m.assigned_role_id is not None
                    else _legacy_role_name(m.role)
                ),
                "role_slug": (
                    m.assigned_role.slug
                    if m.assigned_role_id is not None
                    else m.role
                ),
                "actions": _membership_actions(m),
                "can_configure_machine_types": _can_configure_machine_types(m),
                "is_machine_only": _is_machine_only(m),
                "can_refer": m.can_refer,
                "can_verify": m.can_verify,
                "verified_at": m.verified_at,
                "referrals_enabled": m.makerspace.referrals_enabled,
            }
            for m in memberships
        ],
    }


def _legacy_role_name(role):
    from apps.makerspaces.models import MakerspaceMembership

    try:
        return MakerspaceMembership.Role(role).label
    except ValueError:
        return role.replace("_", " ").title()


class LoginSerializer(TokenObtainPairSerializer):
    token_class = SpaceWorksRefreshToken
    surface = serializers.ChoiceField(
        choices=SocialSurface.choices,
        default=SocialSurface.MEMBER,
        required=False,
    )

    def validate(self, attrs):
        requested_surface = attrs.pop("surface", SocialSurface.MEMBER)
        supplied_username = attrs.get(self.username_field, "")
        if supplied_username and not User.objects.filter(username=supplied_username).exists():
            email_matches = User.objects.filter(
                email__iexact=supplied_username, is_active=True
            ).exclude(email="")
            if email_matches.count() == 1:
                attrs[self.username_field] = email_matches.first().username
        data = super().validate(attrs)  # raises AuthenticationFailed on bad creds/inactive
        from apps.backup.recovery import assert_token_issuance_allowed

        assert_token_issuance_allowed(self.user)
        if self.user.access_status != User.AccessStatus.ACTIVE:
            raise AuthenticationFailed("Account access is restricted.", code="access_denied")
        request = self.context.get("request")
        staff_scope = None
        if requested_surface == SocialSurface.STAFF:
            from apps.accounts.services_social_identity import SocialResolutionError
            from apps.accounts.services_social_login import assert_staff_authority
            from apps.accounts.social_nonces import request_origin
            from apps.makerspaces.cors import staff_origin_is_registered
            from apps.makerspaces.origin_scope import (
                NO_STAFF_ORIGIN_SCOPE,
                staff_origin_scope,
            )

            if request is None or not staff_origin_is_registered(request_origin(request)):
                raise PermissionDenied("Staff login requires a trusted staff origin.")
            try:
                # Password and social login deliberately share this authority decision;
                # a second staff definition would drift from RBAC and tenant scoping.
                assert_staff_authority(self.user, request)
            except SocialResolutionError as exc:
                raise PermissionDenied("Staff access is required.") from exc
            scope = staff_origin_scope(request)
            staff_scope = "platform" if scope is NO_STAFF_ORIGIN_SCOPE else str(scope)

        surface = requested_surface
        if (
            self.user.self_registered_at is not None
            and self.user.email_verified_at is None
        ):
            surface = VERIFICATION_ONLY_SURFACE

        refresh = self.token_class(data["refresh"])
        refresh["surface"] = surface
        if surface == SocialSurface.STAFF:
            refresh["staff_scope"] = staff_scope
        data["refresh"] = str(refresh)
        data["access"] = str(refresh.access_token)
        data["surface"] = surface
        data["user"] = user_payload(self.user, request=request)
        return data


class SpaceWorksTokenRefreshSerializer(TokenRefreshSerializer):
    token_class = SpaceWorksRefreshToken

    def validate(self, attrs):
        def validate_token(refresh):
            validate_auth_generation(refresh)
            user_id = refresh.payload.get(api_settings.USER_ID_CLAIM)
            if not user_id:
                return None
            try:
                user = User.objects.get(
                    **{api_settings.USER_ID_FIELD: user_id}
                )
            except User.DoesNotExist as exc:
                raise AuthenticationFailed(
                    self.error_messages["no_active_account"],
                    code="no_active_account",
                ) from exc
            if not api_settings.USER_AUTHENTICATION_RULE(user):
                raise AuthenticationFailed(
                    self.error_messages["no_active_account"],
                    code="no_active_account",
                )
            return user

        def mint_replacement(refresh, _user):
            data = {"access": str(refresh.access_token)}
            refresh.set_jti()
            refresh.set_exp()
            refresh.set_iat()
            refresh.outstand()
            data["refresh"] = str(refresh)
            return data

        return rotate_refresh_token(
            attrs["refresh"],
            token_class=self.token_class,
            validate=validate_token,
            mint=mint_replacement,
        )
