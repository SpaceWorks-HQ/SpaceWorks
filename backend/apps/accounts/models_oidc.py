"""Generic OpenID Connect providers, so a deployment can bring its own identity server.

Google and Apple are hard-coded because their issuers, JWKS URLs and quirks are fixed.
Everything else worth supporting — Keycloak, Authentik, Azure AD, Okta, Google Workspace
via OIDC — differs only in *configuration*, and `social_jwt.decode_rs256_token` was
already written generically enough to verify any of them. This model is the missing
configuration, not a second verification path.

**Platform-scoped, and it must stay that way.** Identity resolves *before* a makerspace is
selected, so a per-tenant provider key would be unreachable at token-verification time and
would read as disabled for everyone (`test_a6_toggle_scoping.py` pins the same rule for
the built-in providers). A tenant configures its own Telegram/Slack/SMTP credentials
because those fire *after* a makerspace is known; identity cannot work that way.

The provider key stored on `SocialIdentity` is ``oidc:<slug>``, namespaced so a provider
named "google" cannot collide with the built-in one.
"""

from django.core.validators import URLValidator
from django.db import models

OIDC_PREFIX = "oidc:"


def provider_key(slug):
    """The `SocialIdentity.provider` value for an OIDC provider slug."""
    return f"{OIDC_PREFIX}{slug}"


def slug_from_provider_key(provider):
    """The slug for an ``oidc:`` provider key, or None if it is not one."""
    if isinstance(provider, str) and provider.startswith(OIDC_PREFIX):
        return provider[len(OIDC_PREFIX):]
    return None


class OidcProvider(models.Model):
    """One configured OpenID Connect identity provider.

    ``client_secret`` is deliberately absent. Browser login uses authorization code plus
    PKCE, so this deployment is a public client; the token's signature is verified against
    the configured JWKS without introducing a server secret that could leak.
    """

    slug = models.SlugField(max_length=40, unique=True)
    display_name = models.CharField(max_length=80)
    # Exact `iss` claim. Compared verbatim, never normalized -- a provider that issues a
    # trailing slash and a config that omits it are different issuers, and quietly
    # accepting both is how an issuer check stops being a check.
    issuer = models.CharField(max_length=255, validators=[URLValidator(schemes=["https"])])
    jwks_url = models.CharField(max_length=255, validators=[URLValidator(schemes=["https"])])
    # The `aud` claim to require: this deployment's client id at the provider.
    client_id = models.CharField(max_length=255)
    is_enabled = models.BooleanField(default=True)
    # Auto-linking still additionally requires the provider to assert `email_verified`
    # AND the local account's email to be verified -- this only allows it to be
    # considered. An operator running an IdP that does not verify email should clear it.
    allow_auto_link = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["display_name", "id"]
        verbose_name = "OIDC provider"
        verbose_name_plural = "OIDC providers"

    def __str__(self):
        return f"{self.display_name} ({self.slug})"

    @property
    def provider_key(self):
        return provider_key(self.slug)

    @property
    def is_configured(self):
        """Blank configuration fails closed, matching the built-in providers."""
        return bool(
            self.is_enabled
            and self.issuer.strip()
            and self.jwks_url.strip()
            and self.client_id.strip()
        )


def enabled_providers():
    """Configured providers, for the public config payload and the login dispatch."""
    return [row for row in OidcProvider.objects.filter(is_enabled=True) if row.is_configured]


def provider_for_slug(slug):
    """A configured provider, or None. Never returns a disabled or half-filled row."""
    row = OidcProvider.objects.filter(slug=slug, is_enabled=True).first()
    return row if row is not None and row.is_configured else None
