"""One-query validation for the bounded, single-tenant claim session."""

from dataclasses import dataclass
from datetime import datetime, timezone as datetime_timezone

from django.contrib.auth.hashers import UNUSABLE_PASSWORD_PREFIX
from django.db.models import Exists, OuterRef, Q
from django.utils import timezone

from apps.accounts.models_claim import MemberClaimCode
from apps.accounts.models_devices import DeviceGrant
from apps.accounts.models_social import SocialIdentity


@dataclass(frozen=True, slots=True)
class ClaimAuditContext:
    session_id: str
    membership_id: int
    makerspace_id: int
    issued_by_id: int | None
    redemption_ip: str | None
    absolute_expires_at: datetime


class ClaimSessionInvalid(Exception):
    pass


def validated_claim_session(token, *, for_update=False):
    """Return the session with membership/user loaded using exactly one query."""
    social = SocialIdentity.objects.filter(user_id=OuterRef("membership__user_id"))
    grants = DeviceGrant.objects.filter(
        user_id=OuterRef("membership__user_id"),
        status=DeviceGrant.Status.ACTIVE,
    )
    rows = MemberClaimCode.objects.select_related(
        "membership__user", "membership__makerspace", "issued_by"
    ).annotate(has_social_identity=Exists(social), has_active_device_grant=Exists(grants))
    if for_update:
        rows = rows.select_for_update(of=("self",))
    now = timezone.now()
    rows = rows.filter(
        session_id=token.get("claim_session_id"),
        consumed_at__isnull=False,
        revoked_at__isnull=True,
        absolute_expires_at__gt=now,
        membership__status="active",
        membership__user__is_active=True,
        membership__user__access_status="active",
        membership__user__is_walk_in=True,
        membership__user__password__startswith=UNUSABLE_PASSWORD_PREFIX,
        membership__user__email_verified_at__isnull=True,
        has_social_identity=False,
        has_active_device_grant=False,
    ).filter(
        Q(membership__user__phone_verified_at__isnull=True)
        | Q(membership__user__phone_e164__isnull=True)
        | Q(membership__user__phone_e164=""),
        Q(membership__user__telegram_user_id__isnull=True)
        | Q(membership__user__telegram_user_id=""),
    )
    claim = rows.first()
    if claim is None or not _claims_match_row(token, claim):
        raise ClaimSessionInvalid()
    return claim


def audit_context(claim):
    return ClaimAuditContext(
        session_id=str(claim.session_id),
        membership_id=claim.membership_id,
        makerspace_id=claim.membership.makerspace_id,
        issued_by_id=claim.issued_by_id,
        redemption_ip=claim.consumed_ip,
        absolute_expires_at=claim.absolute_expires_at,
    )


def attach_claim_context(user, claim):
    user._claim_audit_context = audit_context(claim)
    return user


def claim_context(user):
    return getattr(user, "_claim_audit_context", None)


def token_payload_for_context(context, user_id):
    return {
        "claim_session_id": context.session_id,
        "claim_membership_id": context.membership_id,
        "claim_makerspace_id": context.makerspace_id,
        "absolute_expires_at": int(context.absolute_expires_at.timestamp()),
        "user_id": user_id,
    }


def _claims_match_row(token, claim):
    try:
        token_deadline = datetime.fromtimestamp(
            int(token["absolute_expires_at"]), tz=datetime_timezone.utc
        )
        return (
            str(token["claim_session_id"]) == str(claim.session_id)
            and int(token["claim_membership_id"]) == claim.membership_id
            and int(token["claim_makerspace_id"]) == claim.membership.makerspace_id
            and int(token["user_id"]) == claim.membership.user_id
            and int(token_deadline.timestamp())
            == int(claim.absolute_expires_at.timestamp())
        )
    except (KeyError, TypeError, ValueError, OverflowError):
        return False
