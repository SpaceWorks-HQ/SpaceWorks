"""Reading the login-method switches, and refusing the ones that would lock people out.

Two halves that must not be confused with each other:

* the **reads**, used at each login boundary, which fail **OPEN** -- a broken capability
  lookup must never be the reason nobody can sign in. Every other capability read on an
  auth path does the same.
* the **lockout guards**, used by the `/control/` form, which are the opposite: they
  refuse a change whenever they cannot prove it is survivable. Switching a method off is
  the dangerous direction, and the accounts it strands are exactly the ones
  forgot-password cannot recover, because they have no usable password to reset.

`social_lockout` already does this per built-in provider. These are the platform-wide
twins: disabling *all* social sign-in strands somebody a single provider never would, and
disabling passwords strands the administrators.
"""

from django.db.models import Exists, OuterRef

from apps.accounts.models import PlatformLoginMethods, User
from apps.accounts.models_social import SocialIdentity


def _switches():
    try:
        return PlatformLoginMethods.load()
    except Exception:  # pragma: no cover - defensive, mirrors the other capability reads
        return PlatformLoginMethods()


def password_login_enabled():
    return bool(_switches().password_enabled)


def social_login_enabled():
    """Covers the built-ins AND every configured OIDC provider.

    They share `SocialLoginView`, one nonce contract and one entry in the public config,
    so a switch that governed only some of them would be a switch an operator could not
    reason about. A deployment that wants one provider and not another disables the
    provider row, which is what `OidcProvider.is_enabled` and the built-in credential
    fields already do.
    """
    return bool(_switches().social_enabled)


def phone_login_enabled():
    return bool(_switches().phone_enabled)


def self_registration_enabled():
    return bool(_switches().self_registration_enabled)


def users_stranded_without_social():
    """Active users whose only credential is a social identity.

    The per-provider check in `social_lockout` cannot answer this: someone holding both
    Google and Apple survives either provider being cleared and is stranded by social
    being switched off entirely.

    `has_usable_password()` inspects the hash prefix and is not expressible in SQL, so
    the query narrows to users who hold any social identity -- a bounded set -- and the
    final check runs in Python.
    """
    candidates = User.objects.filter(is_active=True).filter(
        Exists(SocialIdentity.objects.filter(user=OuterRef("pk")))
    )
    return [user for user in candidates if not user.has_usable_password()]


def superadmins_without_social():
    """Active superadmins holding no social identity.

    With passwords switched off these are the accounts that cannot sign in — and only if
    social sign-in itself stays enabled, which is why the caller checks that first rather
    than this function trying to know both switches at once.

    Narrowed to superadmins on purpose. A member or a staffer stranded by this can be
    recovered by an administrator; an administrator stranded by it cannot be recovered by
    anyone, and `/control/` is the only place the switch can be flipped back. Same floor
    that stops `superadmin_access_enabled` being turned off without Platform Email
    configured: never remove the last route back in.

    Phone is not counted as a rescue. It signs in on the **member surface only** -- the
    refresh claim is a hardcoded "member" and staff surfaces reject it -- so a superadmin
    holding only a verified number still cannot reach the console.
    """
    superadmins = User.objects.filter(is_active=True).filter(
        is_superuser=True
    ) | User.objects.filter(is_active=True, role=User.Role.SUPERADMIN)
    superadmins = superadmins.distinct().annotate(
        has_social=Exists(SocialIdentity.objects.filter(user=OuterRef("pk")))
    )
    return [user for user in superadmins if not user.has_social]
