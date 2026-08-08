"""Verify an ID token from a configured generic OIDC provider.

Deliberately thin: `social_jwt.decode_rs256_token` already does the security-relevant work
(RS256 only, kid required, bounded and cached JWKS fetch with one refresh retry, required
claims, clock skew). Adding a second verification path would mean two places to get RS256
wrong, so this only supplies the per-provider configuration and re-checks the nonce the
same way `social_google` does.
"""

import hmac

from apps.accounts.social_jwt import SocialTokenError, decode_rs256_token


def verify_oidc_token(raw_token, *, nonce, provider_row):
    claims = decode_rs256_token(
        raw_token,
        # Namespaced so the JWKS cache key of a provider slugged "google" cannot collide
        # with the built-in Google entry.
        provider=provider_row.provider_key,
        jwks_url=provider_row.jwks_url,
        # A single exact issuer, never a tuple of tolerated spellings: the built-ins get
        # two only because Google genuinely issues both.
        issuer=provider_row.issuer,
        audience=provider_row.client_id,
    )
    token_nonce = str(claims.get("nonce") or "")
    subject = str(claims.get("sub") or "")
    if not token_nonce or not hmac.compare_digest(token_nonce, nonce) or not subject:
        raise SocialTokenError("Invalid social identity token.")
    return {
        "sub": subject,
        "email": str(claims.get("email") or "").strip().lower(),
        # Only a literal true counts. Some IdPs omit the claim entirely, and a missing
        # claim must never read as verified -- auto-linking keys on this, so a lenient
        # parse here is an account-takeover path.
        "email_verified": claims.get("email_verified") is True
        or str(claims.get("email_verified")).lower() == "true",
        "name": str(claims.get("name") or claims.get("preferred_username") or "").strip(),
        "allow_auto_link": provider_row.allow_auto_link,
    }
