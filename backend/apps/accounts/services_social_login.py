from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import AuthenticationFailed

from apps.accounts import audit_events, rbac
from apps.accounts.models import User
from apps.accounts.models_devices import DeviceGrant, NativeAppRegistration
from apps.accounts.models_social import SocialDelivery, SocialSurface
from apps.accounts.services_device_tokens import (
    assert_mobile_grant_creation_enabled,
    issue_device_token_pair,
)
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
    if scope is NO_STAFF_ORIGIN_SCOPE:
        if rbac.has_any_org_authority(user):
            return
    elif rbac.effective_actions(user, scope):
        return
    raise SocialResolutionError("staff_access_required", 403)


class SocialDeviceGrantRetryRequired(Exception):
    """The pre-grant inputs were burned before device issuance could finish."""


def issue_social_session(
    user, *, surface, delivery, nonce_row, staff_scope=None,
    verified_attestation=None,
):
    assert_social_user_active(user)
    from apps.backup.recovery import assert_token_issuance_allowed

    try:
        assert_token_issuance_allowed(user)
    except AuthenticationFailed as exc:
        if delivery == SocialDelivery.DEVICE and nonce_row.device_grant_id is None:
            raise SocialDeviceGrantRetryRequired from exc
        raise
    if delivery == SocialDelivery.DEVICE:
        grant = nonce_row.device_grant
        if grant is None:
            access, refresh, grant = _issue_first_social_session(
                user, nonce_row.attestation_challenge, verified_attestation
            )
        else:
            with transaction.atomic():
                access, refresh, _family = issue_device_token_pair(user, grant)
        return {"access": access, "refresh": refresh, "device_grant": grant}
    from apps.accounts.tokens import SpaceWorksRefreshToken

    refresh = SpaceWorksRefreshToken.for_user(user)
    refresh["surface"] = surface
    if surface == SocialSurface.STAFF:
        refresh["staff_scope"] = staff_scope or "platform"
    return {"access": str(refresh.access_token), "refresh": str(refresh)}


def _issue_first_social_session(user, challenge, verified_attestation):
    if challenge is None or verified_attestation is None:
        raise SocialDeviceGrantRetryRequired
    try:
        assert_mobile_grant_creation_enabled()
        now = timezone.now()
        with transaction.atomic():
            registration = (
                NativeAppRegistration.objects.select_for_update()
                .filter(
                    pk=challenge.registration_id,
                    status=NativeAppRegistration.Status.APPROVED,
                    platform=challenge.platform,
                    app_id=challenge.app_id,
                    environment=challenge.environment,
                )
                .first()
            )
            if registration is None:
                raise SocialDeviceGrantRetryRequired
            grant = DeviceGrant.objects.create(
                registration=registration,
                user=user,
                platform=challenge.platform,
                app_id=challenge.app_id,
                signing_identity=challenge.signing_identity,
                environment=challenge.environment,
                attestation_subject_fingerprint=audit_events.fingerprint(
                    verified_attestation.subject
                ),
                attested_at=now,
                last_used_at=now,
            )
            audit_events.record_auth_event(
                user, "auth.device_login_succeeded", target=user,
                meta={"grant_hash": audit_events.fingerprint(grant.pk)},
            )
            access, refresh, _family = issue_device_token_pair(user, grant)
    except AuthenticationFailed as exc:
        raise SocialDeviceGrantRetryRequired from exc
    return access, refresh, grant


def social_audit_meta(provider, outcome, subject):
    return {
        "provider": provider,
        "outcome": outcome,
        "subject_hash": audit_events.fingerprint(subject),
    }
