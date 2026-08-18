"""JWT types whose lifetime and authority are bound to one claim-session row."""

from dataclasses import dataclass

from django.utils import timezone
from rest_framework_simplejwt.exceptions import TokenError
from apps.accounts.tokens import SpaceWorksAccessToken, SpaceWorksRefreshToken

from apps.accounts.claim_sessions import attach_claim_context, validated_claim_session
from apps.accounts.services_refresh_tokens import rotate_refresh_token


class ClaimAccessToken(SpaceWorksAccessToken):
    token_type = "claim_access"


class ClaimRefreshToken(SpaceWorksRefreshToken):
    token_type = "claim_refresh"
    access_token_class = ClaimAccessToken


@dataclass(frozen=True, slots=True)
class ClaimTokenPair:
    access: str
    refresh: str


def mint_claim_tokens(claim):
    return _tokens_for_claim(claim)


def rotate_claim_refresh(raw_refresh):
    pair, claim = rotate_refresh_token(
        raw_refresh,
        token_class=ClaimRefreshToken,
        validate=validated_claim_session,
        mint=lambda _old, validated: (_tokens_for_claim(validated), validated),
    )
    return pair, attach_claim_context(claim.membership.user, claim)


def claim_user_from_refresh(raw_refresh, *, require_active=True):
    try:
        token = ClaimRefreshToken(raw_refresh)
        claim = validated_claim_session(token) if require_active else None
    except (TokenError, ClaimSessionError):
        return None
    if claim is None:
        return None
    return attach_claim_context(claim.membership.user, claim)


def _tokens_for_claim(claim):
    if claim.absolute_expires_at is None or claim.absolute_expires_at <= timezone.now():
        raise TokenError("Claim session has expired.")
    from apps.backup.recovery import assert_token_issuance_allowed

    assert_token_issuance_allowed(claim.membership.user)
    refresh = ClaimRefreshToken.for_user(claim.membership.user)
    refresh["surface"] = "member"
    refresh["claim_session_id"] = str(claim.session_id)
    refresh["claim_membership_id"] = claim.membership_id
    refresh["claim_makerspace_id"] = claim.membership.makerspace_id
    refresh["absolute_expires_at"] = int(claim.absolute_expires_at.timestamp())
    refresh["exp"] = int(claim.absolute_expires_at.timestamp())
    return ClaimTokenPair(access=str(refresh.access_token), refresh=str(refresh))


# Kept local so callers do not need to know the validation module's exception type.
from apps.accounts.claim_sessions import ClaimSessionInvalid as ClaimSessionError  # noqa: E402
