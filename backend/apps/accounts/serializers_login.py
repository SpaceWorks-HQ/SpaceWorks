from rest_framework import serializers
from rest_framework.exceptions import AuthenticationFailed, PermissionDenied
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer, TokenRefreshSerializer

from apps.accounts.models import User
from apps.accounts.tokens import SpaceWorksRefreshToken, validate_auth_generation
from apps.accounts.models_social import SocialSurface


VERIFICATION_ONLY_SURFACE = "verification_only"
DEVICE_REFRESH_CLAIMS = ("device_grant_id", "device_family_id")


from apps.accounts.serializers_payload import user_payload

class LoginSerializer(TokenObtainPairSerializer):
    token_class = SpaceWorksRefreshToken
    # No default: an omitted surface means "the server decides". Defaulting to member
    # would silently demote every staff client that has not been updated to send the
    # field, which is a lockout, not a hardening.
    surface = serializers.ChoiceField(
        choices=SocialSurface.choices,
        required=False,
    )

    def validate(self, attrs):
        requested_surface = attrs.pop("surface", None)
        supplied_username = attrs.get(self.username_field, "")
        if supplied_username and not User.objects.filter(username=supplied_username).exists():
            email_matches = User.objects.filter(
                email__iexact=supplied_username, is_active=True
            ).exclude(email="")
            if email_matches.count() == 1:
                attrs[self.username_field] = email_matches.first().username
        from rest_framework_simplejwt.serializers import TokenObtainSerializer
        # Authenticate through Django/axes without minting a refresh token yet.
        data = TokenObtainSerializer.validate(self, attrs)
        if self.user.is_tenant_dump_stub:
            raise AuthenticationFailed(
                self.error_messages["no_active_account"], code="no_active_account"
            )
        from apps.backup.recovery import assert_token_issuance_allowed

        assert_token_issuance_allowed(self.user)
        if self.user.access_status != User.AccessStatus.ACTIVE:
            raise AuthenticationFailed("Account access is restricted.", code="access_denied")
        request = self.context.get("request")
        staff_scope = None
        surface = requested_surface
        if requested_surface != SocialSurface.MEMBER:
            # Derived server-side. A caller may narrow itself to `member`, but it may not
            # be *demoted* to member merely by not sending the field, and it cannot
            # promote itself: assert_staff_authority is the gate either way.
            from apps.accounts.authentication import STAFF_API_SURFACE
            from apps.accounts.services_social_identity import SocialResolutionError
            from apps.accounts.services_social_login import assert_staff_authority
            from apps.accounts.social_nonces import request_origin
            from apps.makerspaces.cors import staff_origin_is_registered
            from apps.makerspaces.origin_scope import (
                NO_STAFF_ORIGIN_SCOPE,
                staff_origin_scope,
            )

            has_staff_origin = request is not None and staff_origin_is_registered(
                request_origin(request)
            )
            try:
                # Password and social login deliberately share this authority decision;
                # a second staff definition would drift from RBAC and tenant scoping.
                assert_staff_authority(self.user, request)
                is_staff_actor = True
            except SocialResolutionError:
                is_staff_actor = False
                if requested_surface == SocialSurface.STAFF:
                    raise PermissionDenied("Staff access is required.") from None
            if is_staff_actor and has_staff_origin:
                # Browser staff session: bind it to the origin it was minted on.
                surface = SocialSurface.STAFF
                scope = staff_origin_scope(request)
                staff_scope = "platform" if scope is NO_STAFF_ORIGIN_SCOPE else str(scope)
            elif is_staff_actor:
                # Origin-less staff caller: `staff` would be unusable, since its
                # per-request check demands a registered origin.
                surface = STAFF_API_SURFACE
            else:
                surface = SocialSurface.MEMBER
        if (
            self.user.self_registered_at is not None
            and self.user.email_verified_at is None
        ):
            surface = VERIFICATION_ONLY_SURFACE

        from apps.accounts.mfa_policy import needs_challenge
        from apps.accounts.mfa_challenges import start
        from apps.accounts.mfa_sessions import context
        if needs_challenge(self.user):
            return start(self.user, context=context(request, surface=surface, staff_scope=staff_scope))
        refresh = self.token_class.for_user(self.user)
        refresh["surface"] = surface
        if surface == SocialSurface.STAFF:
            refresh["staff_scope"] = staff_scope
        data["refresh"] = str(refresh)
        data["access"] = str(refresh.access_token)
        data["surface"] = surface
        data["user"] = user_payload(self.user, request=request)
        return data


