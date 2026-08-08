"""Generic OIDC sign-in (`apps/accounts/models_oidc.py`, `social_oidc.py`).

The verification path is deliberately the same `decode_rs256_token` the built-in providers
use, so these tests concentrate on what is genuinely new: configuration resolution, the
fail-closed rules around half-configured providers, and the auto-link switch an operator
needs when their IdP does not verify email ownership.
"""

import pytest
from django.urls import reverse

from apps.accounts.models import User
from apps.accounts.models_oidc import (
    OidcProvider,
    enabled_providers,
    provider_for_slug,
    provider_key,
    slug_from_provider_key,
)
from apps.accounts.models_social import SocialIdentity
from apps.accounts.services_social_identity import (
    SocialResolutionError,
    resolve_social_identity,
)
from apps.accounts.social_nonces import SocialAuthUnavailable, provider_settings

pytestmark = pytest.mark.django_db


def make_provider(slug="keycloak", **overrides):
    values = {
        "slug": slug,
        "display_name": slug.title(),
        "issuer": "https://id.example.org/realms/main",
        "jwks_url": "https://id.example.org/realms/main/protocol/openid-connect/certs",
        "client_id": "spaceworks",
        "is_enabled": True,
    }
    values.update(overrides)
    return OidcProvider.objects.create(**values)


# --------------------------------------------------------------------------
# Provider key namespacing
# --------------------------------------------------------------------------

def test_the_provider_key_is_namespaced_so_a_slug_cannot_shadow_a_builtin():
    provider = make_provider("google")

    assert provider.provider_key == "oidc:google"
    assert provider.provider_key != "google"
    assert slug_from_provider_key("oidc:google") == "google"
    assert slug_from_provider_key("google") is None


def test_the_identity_row_accepts_a_namespaced_provider_key():
    # The column was 16 chars and enum-constrained before; `oidc:<slug>` needs neither.
    user = User.objects.create_user(username="oidc-user", email="oidc-user@e.com")
    SocialIdentity.objects.create(
        user=user, provider=provider_key("authentik"), provider_sub="sub-1"
    )

    assert SocialIdentity.objects.filter(provider="oidc:authentik").exists()


# --------------------------------------------------------------------------
# Fail-closed configuration
# --------------------------------------------------------------------------

def test_a_disabled_provider_does_not_resolve():
    make_provider("keycloak", is_enabled=False)

    assert provider_for_slug("keycloak") is None
    assert enabled_providers() == []


def test_a_provider_missing_its_client_id_does_not_resolve():
    make_provider("keycloak", client_id="")

    assert provider_for_slug("keycloak") is None


def test_an_unknown_slug_is_unavailable_rather_than_an_error():
    with pytest.raises(SocialAuthUnavailable):
        provider_settings(provider_key("nope"), "web")


def test_provider_settings_returns_the_client_id_as_the_audience():
    provider = make_provider()

    row, audience = provider_settings(provider.provider_key, "web")

    assert row.pk == provider.pk
    assert audience == "spaceworks"


def test_oidc_resolves_without_google_or_apple_being_configured():
    # A deployment running only its own IdP must not be forced to configure a provider
    # it does not use; the platform singleton is never consulted for an oidc: key.
    make_provider()

    row, audience = provider_settings(provider_key("keycloak"), "web")

    assert audience == "spaceworks"


# --------------------------------------------------------------------------
# Auto-link switch
# --------------------------------------------------------------------------

def _claims(email="member@e.com", verified=True, allow_auto_link=True):
    return {
        "sub": "provider-subject-1",
        "email": email,
        "email_verified": verified,
        "name": "A Member",
        "allow_auto_link": allow_auto_link,
    }


def test_auto_link_matches_a_verified_local_account():
    existing = User.objects.create_user(username="known", email="member@e.com")
    existing.email_verified_at = existing.date_joined
    existing.save(update_fields=["email_verified_at"])

    user, outcome = resolve_social_identity(
        provider=provider_key("keycloak"), claims=_claims(), surface="member"
    )

    assert user.pk == existing.pk
    assert outcome == "auto_linked"


def test_a_provider_that_forbids_auto_link_demands_an_explicit_link():
    # The switch exists for an IdP that does not verify email ownership: matching on an
    # unverified address would hand over an existing account.
    existing = User.objects.create_user(username="known2", email="member2@e.com")
    existing.email_verified_at = existing.date_joined
    existing.save(update_fields=["email_verified_at"])

    with pytest.raises(SocialResolutionError) as caught:
        resolve_social_identity(
            provider=provider_key("keycloak"),
            claims=_claims(email="member2@e.com"),
            surface="member",
            allow_auto_link=False,
        )

    assert caught.value.code == "account_link_required"
    assert caught.value.status_code == 409


def test_an_unverified_provider_email_never_auto_links():
    existing = User.objects.create_user(username="known3", email="member3@e.com")
    existing.email_verified_at = existing.date_joined
    existing.save(update_fields=["email_verified_at"])

    with pytest.raises(SocialResolutionError):
        resolve_social_identity(
            provider=provider_key("keycloak"),
            claims=_claims(email="member3@e.com", verified=False),
            surface="member",
        )


def test_a_created_user_gets_a_username_django_will_accept():
    # `oidc:<slug>` contains a colon, which the default username validator rejects.
    from django.contrib.auth.validators import UnicodeUsernameValidator

    user, outcome = resolve_social_identity(
        provider=provider_key("keycloak"),
        claims=_claims(email="fresh@e.com"),
        surface="member",
    )

    assert outcome == "created"
    UnicodeUsernameValidator()(user.username)  # raises if invalid


def test_staff_social_login_still_never_creates_an_account():
    with pytest.raises(SocialResolutionError) as caught:
        resolve_social_identity(
            provider=provider_key("keycloak"),
            claims=_claims(email="nobody@e.com"),
            surface="staff",
        )

    assert caught.value.code == "staff_access_required"


# --------------------------------------------------------------------------
# Public config
# --------------------------------------------------------------------------

def test_an_unconfigured_deployment_publishes_no_oidc_provider(client):
    body = client.get(reverse("public-config")).json()

    assert "oidc:keycloak" not in body.get("social_auth", {})


def test_a_configured_provider_is_published_without_any_secret(client):
    make_provider()

    entry = client.get(reverse("public-config")).json()["social_auth"]["oidc:keycloak"]

    assert entry["client_id"] == "spaceworks"
    assert entry["display_name"] == "Keycloak"
    # There is no client secret to leak: ID-token verification needs only the JWKS.
    assert "client_secret" not in entry
    assert "secret" not in " ".join(entry).lower()
