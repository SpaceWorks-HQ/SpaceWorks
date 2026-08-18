"""The one seam every member-facing identity surface asks before it offers a login.

A deployment runs one of two identity models, and this module is the only place that
answers which:

* **`accounts` on** -- members hold their own accounts. Self sign-up, phone sign-in and
  the built-in consumer providers all work exactly as they always have.
* **`accounts` off** -- there is no member-account *ecosystem*. Nobody signs themselves
  up, and the person record is created by staff at the counter (`walk_in_services`) or
  by the space's own identity provider. Everything downstream is unchanged, because a
  requester is still a real `User` row: `HardwareRequest.requester` is a non-null
  PROTECT FK on a PII-mapped model, and the Hard Rules need a named person on every
  handover. What goes away is self-service, not identity.

Two exemptions are load-bearing and neither is optional:

* **Staff authentication is NEVER gated.** It is core RBAC -- a deployment that could
  switch off its own staff logins could not be administered. This is the same reasoning
  that keeps the staff roster ungated by `membership` (plan A7), and it is why the gate
  below is keyed on the login *surface* and not merely on the provider.
* **A configured OIDC provider is never gated.** `oidc:<slug>` rows are the space's own
  directory (Keycloak, Authentik, Azure AD, Okta) -- an institution's existing accounts,
  not an account ecosystem this deployment runs. They are precisely the identity source
  an accounts-off install is expected to authenticate members against, so gating them
  would remove the alternative at the same moment it removes the default. The built-in
  `google`/`apple` providers are the consumer ecosystem and are gated on the member
  surface.

Reads fail **OPEN**, matching every other capability read on an auth path: a broken
lookup must never lock people out of signing in. The access rules elsewhere fail closed;
that difference is deliberate, and this must not be "fixed" to match them.
"""

import logging

from django.core.cache import cache

from apps.accounts.models_oidc import slug_from_provider_key

logger = logging.getLogger(__name__)

MEMBER_ACCOUNTS_CACHE_KEY = "accounts:member_accounts:last_known_good:v1"


def _cached_member_accounts_enabled():
    try:
        return cache.get(MEMBER_ACCOUNTS_CACHE_KEY)
    except Exception:  # pragma: no cover - a cache outage must not block authentication
        logger.exception("member_accounts_cache_read_failed")
        return None


def member_accounts_enabled():
    """Whether this deployment runs member-facing accounts.

    Read at deployment level rather than per makerspace: sign-up, social sign-in and
    phone login all resolve *before* a makerspace is selected, which is the same reason
    social sign-in must never become a tenant feature. See
    `makerspaces.deployment_modules` for why that reading is the operator's own decision
    on the single-tenant self-host these switches exist for.
    """
    try:
        from apps.makerspaces.deployment_modules import member_accounts_enabled as read

        enabled = bool(read())
    except Exception:
        logger.exception("member_accounts_read_failed")
        cached = _cached_member_accounts_enabled()
        return True if cached is None else bool(cached)

    try:
        cache.set(MEMBER_ACCOUNTS_CACHE_KEY, enabled, timeout=None)
    except Exception:  # pragma: no cover - preserve the successfully resolved policy
        logger.exception("member_accounts_cache_write_failed")
    return enabled


def is_external_provider(provider):
    """Whether `provider` is a configured OIDC provider rather than a built-in.

    Keyed on the `oidc:` namespace rather than on "not google and not apple", so a
    provider slug can never be mistaken for a built-in and a future built-in can never
    be mistaken for a space's own directory. Reuses the one parser that owns that
    namespace, so the two cannot drift.
    """
    return slug_from_provider_key(provider) is not None


def member_login_allowed(provider=None, *, surface="member"):
    """Whether a member-surface login may proceed for this provider.

    `provider=None` covers the credential paths that have no provider at all -- phone
    sign-in and self sign-up.
    """
    if surface != "member":
        return True
    if is_external_provider(provider):
        return True
    return member_accounts_enabled()
