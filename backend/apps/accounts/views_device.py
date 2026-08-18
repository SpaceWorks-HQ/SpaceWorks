from django.conf import settings
from django.contrib.auth import authenticate
from django.db import transaction
from django.utils import timezone
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.exceptions import AuthenticationFailed, PermissionDenied
from rest_framework.permissions import AllowAny, BasePermission, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.accounts import audit_events
from apps.accounts.attestation import (
    AttestationRejected, AttestationUnavailable, challenge_digest,
    create_challenge, verify_attestation,
)
from apps.accounts.login_methods import password_login_enabled
from apps.accounts.models import User
from apps.accounts.models_devices import (
    DeviceAttestationChallenge,
    DeviceGrant,
    NativeAppRegistration,
)
from apps.accounts.serializers import user_payload
from apps.accounts.serializers_device import (
    DeviceChallengeResponseSerializer, DeviceGrantSerializer,
    DeviceIdentitySerializer, DeviceLoginSerializer,
    DeviceLogoutResponseSerializer, DeviceRefreshResponseSerializer,
    DeviceRefreshSerializer, DeviceTokenResponseSerializer,
)
from apps.accounts.services_device_tokens import issue_device_token_pair, rotate_device_refresh
from apps.accounts.services_tokens import revoke_device_grant
from apps.accounts.throttles import DeviceLoginThrottle, DeviceLoginUserThrottle
from apps.hardware_requests.exceptions import ErrorSerializer


def _require_mobile_module():
    """Refuse a new device grant when the deployment does not run mobile apps.

    Checked at grant CREATION only. Existing grants keep working and are revoked
    deliberately, never as a side effect of a capability toggle -- an operator turning
    the module off should stop new pairings, not silently brick every phone already in
    a member's pocket. AuthenticationFailed rather than 404 so the native client's
    existing failure path handles it.
    """
    from apps.makerspaces.deployment_modules import mobile_module_enabled

    if not mobile_module_enabled():
        raise AuthenticationFailed("Mobile device sessions are not enabled.")


def _reject_browser_headers(request):
    if any(
        request.META.get(name)
        for name in ('HTTP_COOKIE', 'HTTP_ORIGIN', 'HTTP_REFERER')
    ):
        raise PermissionDenied("Browser credential transport is not allowed on device auth routes.")


class IsDeviceAccessToken(BasePermission):
    def has_permission(self, request, view):
        _reject_browser_headers(request)
        return bool(
            request.user and request.user.is_authenticated
            and getattr(request, "device_grant", None)
            and request.auth and request.auth.get("token_type") == "access"
        )


class DeviceAttestationChallengeView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "device_attestation_challenge"

    @extend_schema(tags=["Device auth"], auth=[], request=DeviceIdentitySerializer,
        responses={200: DeviceChallengeResponseSerializer, 400: OpenApiResponse(ErrorSerializer), 429: OpenApiResponse(ErrorSerializer), 503: OpenApiResponse(ErrorSerializer)})
    def post(self, request):
        _reject_browser_headers(request)
        serializer = DeviceIdentitySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            raw = create_challenge(**serializer.validated_data)
        except AttestationUnavailable:
            return Response({"detail": "Device attestation is unavailable.", "code": "attestation_unavailable"}, status=503)
        audit_events.record_auth_event(
            None,
            'auth.device_challenge_created',
            meta={
                'platform': serializer.validated_data['platform'],
                'environment': serializer.validated_data['environment'],
                'app_hash': audit_events.fingerprint(
                    serializer.validated_data['app_id']
                ),
            },
        )
        return Response({
            "challenge": raw,
            "expires_in": settings.DEVICE_ATTESTATION_CHALLENGE_TTL_SECONDS,
        })


def _consume_challenge(data):
    now = timezone.now()
    with transaction.atomic():
        challenge = (
            DeviceAttestationChallenge.objects.select_for_update()
            .select_related("registration")
            .filter(challenge_digest=challenge_digest(data["challenge"]))
            .first()
        )
        if challenge is None or challenge.consumed_at is not None:
            return None
        challenge.consumed_at = now
        challenge.save(update_fields=["consumed_at"])
    expected = (challenge.platform, challenge.app_id, challenge.environment)
    actual = (data["platform"], data["app_id"], data["environment"])
    return challenge if challenge.expires_at > now and expected == actual else None


class DeviceLoginView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [DeviceLoginThrottle, DeviceLoginUserThrottle]

    @extend_schema(tags=["Device auth"], auth=[], request=DeviceLoginSerializer,
        responses={200: DeviceTokenResponseSerializer, 401: OpenApiResponse(ErrorSerializer), 403: OpenApiResponse(ErrorSerializer), 503: OpenApiResponse(ErrorSerializer)})
    def post(self, request):
        _reject_browser_headers(request)
        serializer = DeviceLoginSerializer(data=request.data)
        try:
            serializer.is_valid(raise_exception=True)
        except Exception:
            _audit_login_failure(request.data, 'invalid_request')
            raise
        data = serializer.validated_data
        challenge = _consume_challenge(data)
        if challenge is None:
            _audit_login_failure(data, 'invalid_challenge')
            raise AuthenticationFailed("Invalid device credentials or attestation.")
        try:
            verified = verify_attestation(challenge, data["challenge"], data["attestation"])
        except AttestationUnavailable:
            _audit_login_failure(data, 'provider_unavailable')
            return Response({"detail": "Device attestation is unavailable.", "code": "attestation_unavailable"}, status=503)
        except AttestationRejected as exc:
            _audit_login_failure(data, 'attestation_rejected')
            raise AuthenticationFailed("Invalid device credentials or attestation.") from exc
        # A switch that does not actually switch is worse than no switch: an operator
        # believes the password door is closed. Refuse before any credential lookup.
        if not password_login_enabled():
            _audit_login_failure(data, 'password_login_disabled')
            raise AuthenticationFailed("Invalid device credentials or attestation.")
        username = data["username"]
        if not User.objects.filter(username=username).exists():
            matches = User.objects.filter(email__iexact=username, is_active=True).exclude(email="")
            if matches.count() == 1:
                username = matches.first().username
        user = authenticate(request=request, username=username, password=data["password"])
        if not user or user.access_status != User.AccessStatus.ACTIVE:
            _audit_login_failure(data, 'invalid_credentials')
            raise AuthenticationFailed("Invalid device credentials or attestation.")
        _require_mobile_module()
        now = timezone.now()
        with transaction.atomic():
            registration = (
                NativeAppRegistration.objects.select_for_update()
                .filter(
                    pk=challenge.registration_id,
                    status=NativeAppRegistration.Status.APPROVED,
                )
                .first()
            )
            if registration is None:
                _audit_login_failure(data, 'registration_not_approved')
                raise AuthenticationFailed(
                    "Invalid device credentials or attestation."
                )
            grant = DeviceGrant.objects.create(
                registration=registration,
                user=user, platform=challenge.platform, app_id=challenge.app_id,
                signing_identity=challenge.signing_identity, environment=challenge.environment,
                attestation_subject_fingerprint=audit_events.fingerprint(verified.subject),
                attested_at=now, last_used_at=now,
            )
            access, refresh, _ = issue_device_token_pair(user, grant)
        request.device_grant = grant
        audit_events.record_auth_event(user, "auth.device_login_succeeded", target=user,
            meta={"grant_hash": audit_events.fingerprint(grant.pk)})
        return Response({"access": access, "refresh": refresh,
            "user": user_payload(user, request=request),
            "device_grant": DeviceGrantSerializer(grant).data})


class DeviceRefreshView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "device_refresh"

    @extend_schema(tags=["Device auth"], auth=[], request=DeviceRefreshSerializer,
        responses={200: DeviceRefreshResponseSerializer, 400: OpenApiResponse(ErrorSerializer), 401: OpenApiResponse(ErrorSerializer), 429: OpenApiResponse(ErrorSerializer)})
    def post(self, request):
        _reject_browser_headers(request)
        serializer = DeviceRefreshSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        access, refresh, grant, user = rotate_device_refresh(serializer.validated_data["refresh"])
        audit_events.record_auth_event(
            user,
            'auth.device_refresh_rotated',
            target=user,
            meta={'grant_hash': audit_events.fingerprint(grant.pk)},
        )
        return Response({"access": access, "refresh": refresh, "device_grant": DeviceGrantSerializer(grant).data})


class DeviceLogoutView(APIView):
    permission_classes = [IsAuthenticated, IsDeviceAccessToken]

    @extend_schema(tags=["Device auth"], request=None, responses={200: DeviceLogoutResponseSerializer, 401: OpenApiResponse(ErrorSerializer), 403: OpenApiResponse(ErrorSerializer)})
    def post(self, request):
        _reject_browser_headers(request)
        revoke_device_grant(request.device_grant)
        audit_events.record_auth_event(request.user, "auth.device_logout", target=request.user,
            meta={"grant_hash": audit_events.fingerprint(request.device_grant.pk)})
        return Response({"detail": "Device logged out."})


class DeviceGrantListView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(tags=["Device auth"], request=None, responses={200: DeviceGrantSerializer(many=True), 401: OpenApiResponse(ErrorSerializer)})
    def get(self, request):
        grants = DeviceGrant.objects.filter(user=request.user).order_by("-last_used_at")
        return Response(DeviceGrantSerializer(grants, many=True).data)


class DeviceGrantDetailView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(tags=["Device auth"], request=None, responses={204: None, 401: OpenApiResponse(ErrorSerializer), 404: OpenApiResponse(ErrorSerializer)})
    def delete(self, request, grant_id):
        grant = DeviceGrant.objects.filter(pk=grant_id, user=request.user).first()
        if grant is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        revoke_device_grant(grant)
        audit_events.record_auth_event(request.user, "auth.device_grant_revoked", target=request.user,
            meta={"grant_hash": audit_events.fingerprint(grant.pk)})
        return Response(status=status.HTTP_204_NO_CONTENT)


def _audit_login_failure(data, reason):
    audit_events.record_auth_event(
        None,
        'auth.device_login_failed',
        meta={
            'username_hash': audit_events.fingerprint(
                (data or {}).get('username')
            ),
            'reason': reason,
        },
    )
