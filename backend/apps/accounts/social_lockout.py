"""Refuse to disable a social provider that is somebody's only way in (plan A6).

`unlink_social_identity` already protects a user who removes their *own* last
credential. The platform-wide twin had no guard at all: a superadmin clearing Google or
Apple in `/control/` silently locks out every account created through that provider
that never set a password. Those users cannot even use forgot-password -- they have no
usable password to reset, so the one recovery flow that exists will not help them.

So the check runs on the way in, names the number of affected accounts, and points at
the remedy rather than just refusing.
"""

from django.db.models import Exists, OuterRef

from apps.accounts.models import User
from apps.accounts.models_social import SocialIdentity, SocialProvider

GOOGLE_FIELDS = ("google_web_client_id", "google_ios_client_id", "google_android_client_id")


def provider_configured(settings_row, provider):
    """Whether `provider` is resolvable at all with these settings."""
    if settings_row is None:
        return False
    if provider == SocialProvider.GOOGLE:
        return any(
            (getattr(settings_row, field, "") or "").strip() for field in GOOGLE_FIELDS
        )
    return bool(
        (getattr(settings_row, "apple_service_id", "") or "").strip()
        or (getattr(settings_row, "apple_native_app_ids", None) or [])
    )


def users_locked_out_by_disabling(provider):
    """Active users whose ONLY credential is `provider`.

    "Only credential" means an identity for this provider, no identity for any other
    provider, and no usable password. Inactive accounts are excluded: they cannot sign
    in either way, so they are not a reason to block an administrative change.

    `has_usable_password()` is not expressible in SQL (it inspects the hash prefix), so
    the query narrows to the single-identity candidates and the final check runs in
    Python. The candidate set is bounded by "users with a social identity", which is
    small enough that this is not a scan of the user table.
    """
    other_identity = SocialIdentity.objects.filter(user=OuterRef("pk")).exclude(
        provider=provider
    )
    candidates = (
        User.objects.filter(is_active=True, social_identities__provider=provider)
        .annotate(has_other_identity=Exists(other_identity))
        .filter(has_other_identity=False)
        .distinct()
    )
    return [user for user in candidates if not user.has_usable_password()]


def disabling_lockout_message(stored, incoming):
    """The refusal for an edit that would strand accounts, or None when it is safe.

    One predicate for both write surfaces -- the `/control/` form and the staff-console
    `PATCH /admin/platform/social-auth-settings` -- so the API cannot quietly do what the
    form refuses. Only the OFF direction is checked: configuring a provider strands no one.
    """
    for provider in (SocialProvider.GOOGLE, SocialProvider.APPLE):
        if not provider_configured(stored, provider):
            continue
        if provider_configured(incoming, provider):
            continue
        stranded = users_locked_out_by_disabling(provider)
        if stranded:
            return (
                f"Disabling {provider.label} would lock out {len(stranded)} "
                f"account(s) whose only credential is {provider.label} — they have "
                "no usable password, so a password reset cannot recover them. Set a "
                "password for those accounts (or link another provider) first."
            )
    return None
