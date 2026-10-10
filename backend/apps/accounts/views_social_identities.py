"""Authenticated social identity listing, linking and unlinking."""

from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import audit_events
from apps.accounts.models_oidc import slug_from_provider_key
from apps.accounts.models_social import SocialIdentity, SocialProvider
from apps.accounts.serializers_social import SocialIdentitySerializer, SocialLinkSerializer
from apps.accounts.services_social_identity import (
    SocialResolutionError, resolve_social_identity, unlink_social_identity,
)
from apps.accounts.social_jwt import SocialProviderUnavailable, SocialTokenError
from apps.accounts.social_nonces import (
    SocialAuthUnavailable, SocialNonceRejected, consume_social_nonce, provider_settings,
)
from apps.accounts.views_social_helpers import _error
from apps.audit import services as audit
from apps.openapi_errors import errors


class SocialProviderListLinkView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(tags=["Social auth"], responses={200: SocialIdentitySerializer(many=True), **errors(401, 403)})
    def get(self, request):
        rows = SocialIdentity.objects.filter(user=request.user).order_by("provider")
        return Response(SocialIdentitySerializer(rows, many=True).data)

    @extend_schema(tags=["Social auth"], request=SocialLinkSerializer,
        responses={200: SocialIdentitySerializer, **errors(400, 401, 403, 404, 409, 503)})
    def post(self, request):
        serializer = SocialLinkSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            _settings, audience = provider_settings(data["provider"], data["client_platform"])
            consume_social_nonce(request, raw=data["nonce"], provider=data["provider"],
                surface="member", delivery="web", client_platform=data["client_platform"])
            from apps.accounts.views_social import _verify
            claims = _verify(data["provider"], data["id_token"], data["nonce"], audience)
            resolve_social_identity(provider=data["provider"], claims=claims, surface="member",
                apple_name=data.get("apple_name", ""), explicit_user=request.user)
        except SocialAuthUnavailable:
            return _error("social_unavailable", 404)
        except (SocialNonceRejected, SocialTokenError):
            return _error("social_invalid", 401)
        except SocialProviderUnavailable:
            return _error("social_unavailable", 503)
        except SocialResolutionError as exc:
            # Same reasoning as the login view: the nonce was consumed before
            # `_explicit_link` could refuse a walk-in record, so the refusal is recorded
            # against a real actor rather than left as a silent 403.
            audit_events.record_auth_event(
                request.user, "auth.social_identity_link_failed", target=request.user,
                meta={"provider": data["provider"], "reason": exc.code},
            )
            return _error(exc.code, exc.status_code)
        identity = SocialIdentity.objects.get(user=request.user, provider=data["provider"])
        audit.record(request.user, "auth.social_identity_linked", target=request.user,
            meta={"provider": data["provider"], "subject_hash": audit_events.fingerprint(claims["sub"])})
        return Response(SocialIdentitySerializer(identity).data)


class SocialProviderDetailView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(tags=["Social auth"], request=None, responses={204: None, **errors(401, 403, 404, 409)})
    def delete(self, request, provider):
        if provider not in SocialProvider.values and not slug_from_provider_key(provider):
            return _error("identity_not_found", 404)
        try:
            unlink_social_identity(request.user, provider)
        except SocialResolutionError as exc:
            return _error(exc.code, exc.status_code)
        audit.record(request.user, "auth.social_identity_unlinked", target=request.user, meta={"provider": provider})
        return Response(status=status.HTTP_204_NO_CONTENT)


