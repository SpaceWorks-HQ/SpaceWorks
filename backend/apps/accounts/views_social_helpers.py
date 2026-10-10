"""Social provider verification and typed error responses shared by both surfaces."""

from rest_framework.response import Response
from apps.accounts import audit_events
from apps.accounts.social_nonces import SocialAuthUnavailable
from apps.accounts.models_oidc import provider_for_slug, slug_from_provider_key
from apps.accounts.models_social import SocialProvider


def _error(code, status_code):
    messages = {
        "social_unavailable": "Social sign-in is unavailable.",
        "social_invalid": "Social sign-in could not be verified.",
        "account_link_required": "Sign in with an existing credential to link this account.",
        "staff_access_required": "An existing staff account is required.",
        "identity_conflict": "That provider identity is linked to another account.",
        "provider_already_linked": "A different identity from that provider is already linked.",
        "last_credential": "Add another sign-in method before removing this one.",
        "identity_not_found": "That provider is not linked.",
        "access_denied": "Account access is restricted.",
        "registration_disabled": "Account registration is not available.",
        "social_device_restart_required": "Restart device sign-in with a fresh nonce and attestation challenge.",
    }
    return Response({"detail": messages.get(code, messages["social_invalid"]), "code": code}, status=status_code)


def _verify(provider, raw_token, nonce, audience):
    slug = slug_from_provider_key(provider)
    if slug is not None:
        from apps.accounts.social_oidc import verify_oidc_token

        row = provider_for_slug(slug)
        if row is None:
            raise SocialAuthUnavailable
        return verify_oidc_token(raw_token, nonce=nonce, provider_row=row)
    if provider == SocialProvider.GOOGLE:
        from apps.accounts.social_google import verify_google_token
        return verify_google_token(raw_token, nonce=nonce, audience=audience)
    from apps.accounts.social_apple import verify_apple_token
    return verify_apple_token(raw_token, nonce=nonce, audience=audience)


def _audit_failure(provider, reason):
    audit_events.record_auth_event(None, "auth.social_login_failed", meta={"provider": provider, "reason": reason})
