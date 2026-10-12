import hashlib

from django.conf import settings
from django.utils.crypto import constant_time_compare

from apps.accounts.social_jwt import SocialTokenError, decode_rs256_token


def verify_apple_token(raw_token, *, nonce, audience):
    claims = decode_rs256_token(
        raw_token,
        provider="apple",
        jwks_url=settings.SOCIAL_APPLE_JWKS_URL,
        issuer="https://appleid.apple.com",
        audience=audience,
    )
    token_nonce = str(claims.get("nonce") or "")
    hashed_nonce = hashlib.sha256(nonce.encode()).hexdigest()
    subject = str(claims.get("sub") or "")
    if not subject or not (
        constant_time_compare(token_nonce, nonce)
        or constant_time_compare(token_nonce, hashed_nonce)
    ):
        raise SocialTokenError("Invalid social identity token.")
    email = str(claims.get("email") or "").strip().lower()
    verified = claims.get("email_verified") is True or str(
        claims.get("email_verified")
    ).lower() == "true"
    return {
        "sub": subject,
        "email": email,
        "email_verified": bool(email and verified),
        "name": "",
    }
