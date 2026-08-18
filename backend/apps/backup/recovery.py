import uuid

from django.contrib.auth import get_user_model
from django.contrib.sessions.models import Session
from django.contrib.auth.hashers import make_password
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import AuthenticationFailed, PermissionDenied, ValidationError
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken

from apps.audit import services as audit
from apps.backup.models import DeploymentRecoveryState, RestoreOperation


RESIDUAL_RISK = (
    "I understand that this blanket acknowledgement may restore authority removed after "
    "the archive was created. On a disaster restore, the destroyed live database cannot "
    "be compared and identity links may have been reintroduced."
)


def is_recovery_principal(user, state=None):
    if not getattr(user, "is_authenticated", False):
        return False
    state = state or DeploymentRecoveryState.objects.filter(pk=1).only(
        "recovery_principal_id"
    ).first()
    return bool(state and user.pk == state.recovery_principal_id)


def can_read_recovery_state(user):
    if not getattr(user, "is_authenticated", False):
        return False
    is_active_superadmin = bool(
        user.is_active
        and user.access_status == user.AccessStatus.ACTIVE
        and not getattr(user, "must_change_password", False)
        and (user.is_superuser or user.role == user.Role.SUPERADMIN)
    )
    return is_active_superadmin or is_recovery_principal(user)


def assert_principal_allowed(user):
    state = DeploymentRecoveryState.objects.filter(pk=1).only(
        "mode", "recovery_principal_id"
    ).first()
    if state and state.mode == DeploymentRecoveryState.Mode.QUARANTINED:
        if not is_recovery_principal(user, state):
            raise AuthenticationFailed(
                "Only the out-of-band recovery superadmin may authenticate during quarantine.",
                code="deployment_quarantined",
            )


assert_token_issuance_allowed = assert_principal_allowed


@transaction.atomic
def enter_quarantine(restore, reason):
    now = timezone.now()
    state = _locked_state()
    state.mode = DeploymentRecoveryState.Mode.QUARANTINED
    state.auth_generation = uuid.uuid4()
    state.active_restore = restore
    state.recovery_principal = None
    state.quarantine_reason = str(reason)
    state.quarantined_at = now
    state.acknowledged_at = None
    state.acknowledged_by = None
    state.acknowledgement = ""
    state.save()

    User = get_user_model()
    User.objects.all().update(password=make_password(None))
    Session.objects.all().delete()
    _invalidate_tokens(now)

    from apps.accounts.models_claim import MemberClaimCode
    from apps.accounts.models import EmailVerificationChallenge, OidcBrowserAttempt
    from apps.accounts.models_devices import (
        DeviceAttestationChallenge,
        DeviceGrant,
        DeviceRefreshFamily,
        DeviceRefreshToken,
    )
    from apps.accounts.models_phone import PhoneVerificationChallenge
    from apps.accounts.models_password_reset import PasswordResetEnvelope, PasswordResetEnvelopeStatus
    from apps.accounts.models_social import SocialLoginNonce
    from apps.apiclients.models import ApiClient
    from apps.makerspaces.models import Makerspace, generate_publishable_key

    ApiClient.objects.filter(is_active=True).update(is_active=False)
    DeviceGrant.objects.update(status=DeviceGrant.Status.REVOKED, revoked_at=now)
    DeviceRefreshFamily.objects.filter(revoked_at__isnull=True).update(revoked_at=now)
    DeviceRefreshToken.objects.filter(blacklisted_at__isnull=True).update(blacklisted_at=now)
    MemberClaimCode.objects.filter(revoked_at__isnull=True).update(revoked_at=now)
    for challenge in (
        DeviceAttestationChallenge,
        EmailVerificationChallenge,
        OidcBrowserAttempt,
        PhoneVerificationChallenge,
        SocialLoginNonce,
    ):
        challenge.objects.filter(consumed_at__isnull=True).update(consumed_at=now)
    for makerspace in Makerspace.objects.only("pk"):
        Makerspace.objects.filter(pk=makerspace.pk).update(
            public_api_key=generate_publishable_key()
        )
    PasswordResetEnvelope.objects.update(
        status=PasswordResetEnvelopeStatus.DISCARDED,
        digest_is_live=False,
        digest="",
        claim_owner="",
        claim_expires_at=None,
        terminal_at=now,
    )
    restore.stage = RestoreOperation.Stage.RESTORED_QUARANTINED
    restore.completed_at = now
    restore.save(update_fields=("stage", "completed_at", "updated_at"))
    audit.record(
        restore.requested_by,
        "backup.restore_quarantined",
        target=restore,
        meta={"reason": str(reason), "auth_generation": str(state.auth_generation)},
    )
    return state


def _invalidate_tokens(now):
    existing = set(BlacklistedToken.objects.values_list("token_id", flat=True))
    BlacklistedToken.objects.bulk_create(
        [BlacklistedToken(token=token) for token in OutstandingToken.objects.exclude(pk__in=existing)],
        ignore_conflicts=True,
    )


@transaction.atomic
def set_recovery_principal(user, raw_password):
    User = get_user_model()
    locked = User.objects.select_for_update().get(pk=user.pk)
    if not (locked.is_superuser or locked.role == User.Role.SUPERADMIN):
        raise ValidationError("The recovery principal must already be a superadmin.")
    locked.is_active = True
    locked.is_staff = True
    locked.is_superuser = True
    locked.role = User.Role.SUPERADMIN
    locked.access_status = User.AccessStatus.ACTIVE
    locked.must_change_password = False
    locked.set_password(raw_password)
    locked.save()
    state = _locked_state()
    if state.mode != DeploymentRecoveryState.Mode.QUARANTINED:
        raise ValidationError("The deployment is not quarantined.")
    state.recovery_principal = locked
    state.save(update_fields=("recovery_principal", "updated_at"))
    audit.record(
        locked,
        "backup.recovery_superadmin_established",
        target=state,
        meta={"source": "privileged_host_command"},
    )
    return locked


@transaction.atomic
def acknowledge_quarantine(actor, acknowledgement):
    state = _locked_state()
    if state.mode != DeploymentRecoveryState.Mode.QUARANTINED:
        raise ValidationError("The deployment is not quarantined.")
    if not is_recovery_principal(actor, state):
        raise PermissionDenied("Only the recovered superadmin may acknowledge quarantine.")
    if acknowledgement != RESIDUAL_RISK:
        raise ValidationError({"acknowledgement": "The residual-risk acknowledgement must match exactly."})
    now = timezone.now()
    state.mode = DeploymentRecoveryState.Mode.NORMAL
    state.acknowledged_at = now
    state.acknowledged_by = actor
    state.acknowledgement = acknowledgement
    state.save()
    audit.record(
        actor,
        "backup.quarantine_acknowledged",
        target=state,
        meta={"residual_risk": acknowledgement, "restore_id": str(state.active_restore_id or "")},
    )
    return state


def _locked_state():
    DeploymentRecoveryState.objects.get_or_create(pk=1)
    return DeploymentRecoveryState.objects.select_for_update().get(pk=1)
