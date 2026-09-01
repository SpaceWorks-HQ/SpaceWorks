"""Issue and revoke physically handed member claim credentials."""

import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.core.validators import validate_ipv46_address
from django.db import transaction
from django.utils import timezone

from apps.accounts import rbac
from apps.accounts.models import MemberClaimCode, User
from apps.accounts.models_devices import DeviceGrant
from apps.accounts.models_social import SocialIdentity
from apps.accounts.transition_services import register_walk_in_revocation_hook
from apps.audit import services as audit
from apps.makerspaces.models import MakerspaceMembership
from apps.makerspaces.staff_authority import lock_and_validate_staff_authority

MAX_FAILED_ATTEMPTS = 5
_CODE_PATTERN = re.compile(r"^MC1-(?P<id>[1-9][0-9]*)-(?P<secret>[A-Z2-9]{4}(?:-[A-Z2-9]{4}){3})$")
_SECRET_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


class ClaimCodeError(Exception):
    pass


class ClaimCodeIneligible(Exception):
    pass


@dataclass(frozen=True)
class IssuedClaimCode:
    claim: MemberClaimCode
    code: str


def _normalized_code(value: str) -> str:
    return "".join((value or "").split()).upper()


def _digest(value: str) -> str:
    return hmac.new(
        settings.SECRET_KEY.encode("utf-8"),
        b"member-claim-code:v1\0" + _normalized_code(value).encode("ascii"),
        hashlib.sha256,
    ).hexdigest()


def _raw_code(claim_id: int) -> str:
    secret = "".join(secrets.choice(_SECRET_ALPHABET) for _ in range(16))
    groups = "-".join(secret[index : index + 4] for index in range(0, 16, 4))
    return f"MC1-{claim_id}-{groups}"


def _locked_target(makerspace_id: int, membership_id: int):
    membership = (
        MakerspaceMembership.objects.select_for_update()
        .filter(pk=membership_id, makerspace_id=makerspace_id, status="active")
        .first()
    )
    if membership is None:
        raise ClaimCodeIneligible()
    user = User.objects.select_for_update().get(pk=membership.user_id)
    if not _credential_free_walk_in(user):
        raise ClaimCodeIneligible()
    membership.user = user
    return membership


def _credential_free_walk_in(user: User) -> bool:
    return bool(
        not user.is_tenant_dump_stub
        and user.is_active
        and user.access_status == User.AccessStatus.ACTIVE
        and user.is_walk_in
        and not user.has_usable_password()
        and not (user.phone_e164 and user.phone_verified_at)
        and not user.telegram_user_id
        and user.email_verified_at is None
        and not SocialIdentity.objects.filter(user=user).exists()
        and not DeviceGrant.objects.filter(
            user=user, status=DeviceGrant.Status.ACTIVE
        ).exists()
    )


def issue_claim_code(*, actor, makerspace_id: int, membership_id: int) -> IssuedClaimCode:
    """Mint one digest-only code after locked issuer and target revalidation."""
    now = timezone.now()
    with transaction.atomic():
        authority = lock_and_validate_staff_authority(
            actor=actor,
            makerspace_id=makerspace_id,
            allowed_actions=frozenset({rbac.Action.ISSUE_DIRECT_LOAN}),
        )
        membership = _locked_target(authority.makerspace.pk, membership_id)

        # One current physical credential per membership. This also makes re-issuing a
        # code terminate the eventual D5 session bound to an older code row.
        existing = list(
            MemberClaimCode.objects.select_for_update().filter(
                membership=membership, revoked_at__isnull=True
            )
        )
        for prior in existing:
            _revoke_locked_claim(prior, now=now, actor=authority.actor)

        claim = MemberClaimCode.objects.create(
            membership=membership,
            issued_by=authority.actor,
            expires_at=now
            + timedelta(seconds=settings.MEMBER_CLAIM_CODE_TTL_SECONDS),
            # A unique one-transaction placeholder lets the database assign the id that
            # makes mistyped codes attributable without ever storing the final secret.
            code_digest=secrets.token_hex(32),
        )
        code = _raw_code(claim.pk)
        claim.code_digest = _digest(code)
        claim.save(update_fields=["code_digest"])
        audit.record(
            authority.actor,
            "member.claim_code_issued",
            makerspace=authority.makerspace,
            target=membership,
            meta={"expires_at": claim.expires_at.isoformat()},
        )
    return IssuedClaimCode(claim=claim, code=code)


def active_claim_codes(*, actor, makerspace_id: int):
    """Return usable, unconsumed rows only; raw codes are unrecoverable by design."""
    allowed = rbac.makerspaces_for_action(actor, rbac.Action.ISSUE_DIRECT_LOAN)
    if allowed is not rbac.ALL and makerspace_id not in allowed:
        from rest_framework.exceptions import PermissionDenied

        raise PermissionDenied()
    return (
        MemberClaimCode.objects.select_related("membership__user", "issued_by")
        .filter(
            membership__makerspace_id=makerspace_id,
            consumed_at__isnull=True,
            revoked_at__isnull=True,
            expires_at__gt=timezone.now(),
        )
        .order_by("-issued_at")
    )


def revoke_claim_code(*, actor, makerspace_id: int, claim_id: int) -> MemberClaimCode:
    """Revoke a code (and D5 session bound to its row) under locked authority."""
    with transaction.atomic():
        authority = lock_and_validate_staff_authority(
            actor=actor,
            makerspace_id=makerspace_id,
            allowed_actions=frozenset({rbac.Action.ISSUE_DIRECT_LOAN}),
        )
        claim = (
            MemberClaimCode.objects.select_for_update(of=("self",))
            .select_related("membership__user", "issued_by", "revoked_by")
            .filter(pk=claim_id, membership__makerspace=authority.makerspace)
            .first()
        )
        if claim is None:
            from rest_framework.exceptions import NotFound

            raise NotFound()
        if claim.revoked_at is None:
            _revoke_locked_claim(
                claim, now=timezone.now(), actor=authority.actor
            )
            audit.record(
                authority.actor,
                "member.claim_code_revoked",
                makerspace=authority.makerspace,
                target=claim.membership,
            )
        return claim


def consume_claim_code(
    raw_code: str, *, redemption_ip: str, makerspace_id: int | None = None
) -> MemberClaimCode:
    """Consume and validate a code for D5 without minting a session.

    Post-consumption refusals deliberately commit ``consumed_at`` and their audit before
    raising. Wrong-code counters do the same via a deferred raise.
    """
    validate_ipv46_address(redemption_ip)
    normalized = _normalized_code(raw_code)
    match = _CODE_PATTERN.fullmatch(normalized)
    failure = None
    resolved = None
    with transaction.atomic():
        claim = None
        if match is not None:
            claim = (
                MemberClaimCode.objects.select_for_update()
                .select_related("membership__makerspace")
                .filter(pk=int(match.group("id")))
                .first()
            )
        if claim is None:
            failure = ClaimCodeError()
        elif claim.consumed_at is not None or claim.failed_attempts >= MAX_FAILED_ATTEMPTS:
            _audit_redemption(claim, "member.claim_code_redemption_refused", redemption_ip, "used")
            failure = ClaimCodeError()
        elif not hmac.compare_digest(claim.code_digest, _digest(normalized)):
            claim.failed_attempts += 1
            updates = ["failed_attempts"]
            if claim.failed_attempts >= MAX_FAILED_ATTEMPTS:
                claim.consumed_at = timezone.now()
                claim.consumed_ip = redemption_ip
                updates.extend(["consumed_at", "consumed_ip"])
            claim.save(update_fields=updates)
            _audit_redemption(claim, "member.claim_code_redemption_failed", redemption_ip, "mismatch")
            failure = ClaimCodeError()
        else:
            now = timezone.now()
            claim.consumed_at = now
            claim.consumed_ip = redemption_ip
            claim.save(update_fields=["consumed_at", "consumed_ip"])
            try:
                membership = _locked_target(
                    claim.membership.makerspace_id, claim.membership_id
                )
            except ClaimCodeIneligible:
                _audit_redemption(claim, "member.claim_code_redemption_refused", redemption_ip, "ineligible")
                failure = ClaimCodeError()
            else:
                claim.membership = membership
                if makerspace_id is not None and claim.membership.makerspace_id != makerspace_id:
                    _audit_redemption(claim, "member.claim_code_redemption_refused", redemption_ip, "wrong_makerspace")
                    failure = ClaimCodeError()
                elif claim.revoked_at is not None or claim.expires_at <= now:
                    reason = "revoked" if claim.revoked_at is not None else "expired"
                    _audit_redemption(claim, "member.claim_code_redemption_refused", redemption_ip, reason)
                    failure = ClaimCodeError()
                else:
                    claim.absolute_expires_at = now + timedelta(
                        seconds=settings.MEMBER_CLAIM_SESSION_TTL_SECONDS
                    )
                    claim.save(update_fields=["absolute_expires_at"])
                    _audit_redemption(claim, "member.claim_code_consumed", redemption_ip, "accepted")
                    resolved = claim
    if failure is not None:
        raise failure
    return resolved


def _audit_redemption(claim, action: str, redemption_ip: str, outcome: str) -> None:
    audit.record(
        None,
        action,
        makerspace=claim.membership.makerspace,
        target=claim.membership,
        meta={"redemption_ip": redemption_ip, "outcome": outcome},
    )


def _revoke_transition_claim_state(user: User, transitioned_at) -> None:
    claims = list(
        MemberClaimCode.objects.select_for_update().filter(
            membership__user=user, revoked_at__isnull=True
        )
    )
    for claim in claims:
        _revoke_locked_claim(claim, now=transitioned_at, actor=None)


def _revoke_locked_claim(claim, *, now, actor) -> None:
    """Revoke a locked claim before locking only its provenanced presence rows."""
    claim.revoked_at = now
    claim.revoked_by = actor
    claim.save(update_fields=["revoked_at", "revoked_by"])
    from apps.presence.services import end_sessions_for_claim

    end_sessions_for_claim(claim, ended_at=now, actor=actor)


def register_transition_revocation() -> None:
    register_walk_in_revocation_hook(
        "member-claim-state", _revoke_transition_claim_state
    )
