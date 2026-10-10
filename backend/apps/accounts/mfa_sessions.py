"""Finish the original login after MFA without accepting client authority claims."""

from django.utils import timezone
from rest_framework.exceptions import AuthenticationFailed, PermissionDenied

from apps.accounts import audit_events
from apps.accounts.models_devices import DeviceAttestationChallenge, DeviceGrant, NativeAppRegistration
from apps.accounts.serializers_device import DeviceGrantSerializer
from apps.accounts.services_device_tokens import issue_device_token_pair, assert_mobile_grant_creation_enabled
from apps.accounts.services_social_login import assert_staff_authority
from apps.accounts.tokens import SpaceWorksRefreshToken


def context(request, *, surface, staff_scope=None, device=None):
    from apps.accounts.social_nonces import request_origin
    origin = request_origin(request) if request is not None else ""
    if surface == "control":
        origin = request.build_absolute_uri("/").rstrip("/")
    return {"surface": surface, "staff_scope": staff_scope,
            "origin": origin, **({"device": device} if device else {})}


def device_context(challenge, verified, grant=None):
    return {"attestation_id": str(challenge.pk) if challenge else None,
            "subject_hash": audit_events.fingerprint(verified.subject) if verified else "",
            "grant_id": str(grant.pk) if grant else None}


def issue_session(user, data, request):
    from apps.accounts.serializers import user_payload
    surface = data["surface"]
    if surface == "control":
        return {"mfa_version": str(user._mfa_verified_version)}
    if surface in ("staff", "staff_api"):
        from apps.accounts.services_social_identity import SocialResolutionError
        try:
            assert_staff_authority(user, request)
        except SocialResolutionError as exc:
            raise PermissionDenied("Staff access is required.") from exc
    device = data.get("device")
    if device:
        from apps.accounts.views_device import _reject_browser_headers
        _reject_browser_headers(request)
        assert_mobile_grant_creation_enabled()
        if device.get("grant_id"):
            grant = DeviceGrant.objects.select_for_update().filter(
                pk=device["grant_id"], user=user, status=DeviceGrant.Status.ACTIVE,
                registration__status=NativeAppRegistration.Status.APPROVED,
            ).first()
        else:
            attestation = DeviceAttestationChallenge.objects.get(pk=device["attestation_id"])
            registration = NativeAppRegistration.objects.select_for_update().filter(
                pk=attestation.registration_id, status=NativeAppRegistration.Status.APPROVED,
            ).first()
            grant = None
            if registration:
                grant = DeviceGrant.objects.create(
                    registration=registration, user=user, platform=attestation.platform,
                    app_id=attestation.app_id, environment=attestation.environment,
                    signing_identity=attestation.signing_identity,
                    attestation_subject_fingerprint=device["subject_hash"],
                    attested_at=timezone.now(), last_used_at=timezone.now(),
                )
        if grant is None:
            raise AuthenticationFailed("Device authorization is no longer active.")
        access, refresh, _ = issue_device_token_pair(user, grant)
        request.device_grant = grant
        audit_events.record_auth_event(user, "auth.device_login_succeeded", target=user)
        return {"access": access, "refresh": refresh, "surface": surface,
                "user": user_payload(user, request=request), "device_grant": DeviceGrantSerializer(grant).data}
    refresh = SpaceWorksRefreshToken.for_user(user)
    refresh["surface"] = surface
    if surface == "staff":
        refresh["staff_scope"] = data.get("staff_scope") or "platform"
    return {"access": str(refresh.access_token), "refresh": str(refresh), "surface": surface,
            "user": user_payload(user, request=request)}
