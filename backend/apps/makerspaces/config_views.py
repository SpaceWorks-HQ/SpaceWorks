from django.conf import settings
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.integrations.email import email_enabled


class PublicConfigSerializer(serializers.Serializer):
    email_enabled = serializers.BooleanField()
    public_image_max_bytes = serializers.IntegerField()
    social_auth = serializers.DictField(required=False)
    phone_login = serializers.DictField(required=False)
    password_login = serializers.DictField(required=False)
    self_registration = serializers.DictField(required=False)
    member_accounts = serializers.DictField(required=False)


class PublicConfigView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = []

    @extend_schema(
        tags=["Platform"],
        summary="Return frontend-safe platform configuration",
        responses={200: PublicConfigSerializer},
    )
    def get(self, request, *args, **kwargs):
        payload = {
            "email_enabled": email_enabled(),
            "public_image_max_bytes": settings.PUBLIC_IMAGE_MAX_BYTES,
        }
        from apps.accounts.login_methods import (
            password_login_enabled,
            phone_login_enabled,
            self_registration_enabled,
            social_login_enabled,
        )
        from apps.accounts.member_identity import member_accounts_enabled

        member_accounts = member_accounts_enabled()
        from apps.accounts.models_social import PlatformSocialAuthSettings

        configured = {}
        # One switch governs the built-ins and every configured OIDC provider, because
        # they share one endpoint. With it off, none of them are advertised -- the login
        # screen must not render a provider whose endpoint 404s.
        if social_login_enabled():
            social = PlatformSocialAuthSettings.objects.filter(pk=1).first()
            if social and social.google_web_client_id:
                configured["google"] = {
                    "enabled": True,
                    "web_client_id": social.google_web_client_id,
                }
            if social and social.apple_service_id:
                configured["apple"] = {
                    "enabled": True,
                    "service_id": social.apple_service_id,
                }
            from apps.accounts.models_oidc import enabled_providers

            for row in enabled_providers():
                # Namespaced under the same key so the login screen renders every
                # provider from one list. Only the client id is published -- it is a
                # public value by design, and there is no secret to leak because
                # ID-token verification needs none.
                configured[row.provider_key] = {
                    "enabled": True,
                    "display_name": row.display_name,
                    "client_id": row.client_id,
                    "issuer": row.issuer,
                }
        if configured:
            payload["social_auth"] = configured
        # Omitted entirely when SMS is unconfigured, exactly like social_auth above: an
        # absent key keeps the dormant payload byte-for-byte unchanged, and a login
        # screen that renders a phone tab it cannot service is worse than no tab.
        from apps.integrations.sms import sms_configured

        if sms_configured() and member_accounts and phone_login_enabled():
            # Phone sign-in has no staff surface at all -- the refresh claim is a
            # hardcoded "member" -- so with member accounts off there is nothing left
            # for the tab to do, and the endpoint behind it 404s.
            payload["phone_login"] = {"enabled": True}
        # Emitted only when NOT the default, keeping the payload byte-for-byte unchanged
        # for every deployment that has not touched these switches. Password sign-in is
        # the one a login screen must be told about explicitly: with it off there is no
        # form to render at all, and an empty screen with no explanation is the worst
        # possible answer.
        if not password_login_enabled():
            payload["password_login"] = {"enabled": False}
        if not self_registration_enabled():
            payload["self_registration"] = {"enabled": False}
        if not member_accounts:
            # Emitted ONLY when disabled. `accounts` defaults on, so every existing
            # deployment keeps a byte-for-byte identical payload, and the key's presence
            # is itself the signal -- the same shape as `geofence_enabled`.
            #
            # This is discovery, not enforcement. `social_auth` still advertises the
            # built-in providers because the STAFF login screen reads the same endpoint;
            # what stops a member-surface login is the check in `SocialLoginView`.
            payload["member_accounts"] = {"enabled": False}
        return Response(payload)
