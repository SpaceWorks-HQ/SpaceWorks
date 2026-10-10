"""Apple's literal and hashed nonce contracts need no Apple developer account."""

import hashlib

import pytest

from apps.accounts import social_apple
from apps.accounts.social_jwt import SocialTokenError


@pytest.mark.parametrize("hashed", [False, True])
def test_apple_accepts_literal_or_hashed_nonce(monkeypatch, hashed):
    nonce = "random-challenge"
    claims = {
        "sub": "apple-user", "nonce": hashlib.sha256(nonce.encode()).hexdigest() if hashed else nonce,
        "email": " USER@Example.Org ", "email_verified": "true",
    }
    seen = {}

    def decode(token, **kwargs):
        seen.update(kwargs)
        return claims

    monkeypatch.setattr(social_apple, "decode_rs256_token", decode)
    identity = social_apple.verify_apple_token("signed-token", nonce=nonce, audience="app-id")
    assert seen["issuer"] == "https://appleid.apple.com"
    assert seen["audience"] == "app-id"
    assert identity == {"sub": "apple-user", "email": "user@example.org", "email_verified": True, "name": ""}


@pytest.mark.parametrize("claims", [
    {"sub": "user", "nonce": "wrong"}, {"sub": "user", "nonce": "é"},
    {"nonce": "challenge"}, {"sub": "user"},
])
def test_invalid_apple_claims_are_rejected_not_a_500(monkeypatch, claims):
    monkeypatch.setattr(social_apple, "decode_rs256_token", lambda *a, **k: claims)
    with pytest.raises(SocialTokenError):
        social_apple.verify_apple_token("token", nonce="challenge", audience="app")
