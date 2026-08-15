"""JWT types whose lifetime and authority are bound to one claim-session row."""

from dataclasses import dataclass

from django.utils import timezone
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken

from apps.accounts.claim_sessions import attach_claim_context, validated_claim_session


class ClaimAccessToken(AccessToken):
    token_type = "claim_access"


class ClaimRefreshToken(RefreshToken):
    token_type = "claim_refresh"
    access_token_class = ClaimAccessToken


@dataclass(frozen=True, slots=True)
class ClaimTokenPair:
    access: str
    refresh: str


def mint_claim_tokens(claim):
    return _tokens_for_claim(claim)


def rotate_claim_refresh(raw_refresh):
    old = ClaimRefreshToken(raw_refresh)
    claim = validated_claim_session(old)
    old.blacklist()
    return _tokens_for_claim(claim), attach_claim_context(
        claim.membership.user, claim
    )


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
