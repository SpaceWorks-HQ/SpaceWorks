"""Who may submit a borrow request — the single answer, in one place.

Three states, and they are DERIVED, not stored. Only ``anonymous_requests_enabled`` is a
column; the rest falls out of whether the ``membership`` module is installed:

===========  =====================  ============================================
`membership` `anonymous_requests_…` who may submit
===========  =====================  ============================================
on           off                    ``members``  — an active MakerspaceMembership
off          off                    ``accounts`` — any active authenticated account
off          on                     ``anyone``   — no account at all
on           **on**                 impossible — see below
===========  =====================  ============================================

The fourth row is the reason this module exists. `RequestSubmitView` takes the anonymous
branch *before* it reaches any membership guard, so a row carrying both settings would let
a stranger walk straight past the membership requirement the operator had just switched on
— the opposite of what enabling `membership` means. Turning one on therefore turns the
other off, and it is enforced at three depths so no write path can reconstruct the state:

1. ``Makerspace.save()`` calls :func:`reconcile_enabled_modules` — the model cannot be
   persisted in the impossible state by ANY caller (module install/uninstall, profile
   application, the ``/control/`` capability matrix, ``setup_instance``, ``seed_demo``, a
   plain ``obj.save()``).
2. :func:`set_anonymous_requests` is the only *deliberate* writer, and it takes the row
   lock so a concurrent membership install cannot land between its check and its save.
3. :func:`anonymous_requests_allowed` re-derives the answer at request time, so a row
   written by raw SQL or restored from an old backup still fails closed.

Forced, never refused: refusing a membership install because of an unrelated public-access
flag would block a legitimate module change from the console and the setup tick list. The
change is audited with the before/after policy so it is never silent.
"""

MEMBERSHIP_MODULE = "membership"

MEMBERS = "members"
ACCOUNTS = "accounts"
ANYONE = "anyone"

POLICY_LABELS = {
    MEMBERS: "active members of this makerspace",
    ACCOUNTS: "anyone with a signed-in account",
    ANYONE: "anyone, no account needed",
}


def membership_installed(enabled_modules) -> bool:
    """Pure predicate over the stored key list.

    Deliberately NOT ``platform.module_enabled``: that also asks whether the deployment
    still ships the app, and this is the fail-closed direction. A tenant that asked for
    membership must not have strangers admitted just because the app is tombstoned, and
    the model layer cannot import ``platform`` anyway (``platform`` imports the models).
    """
    return MEMBERSHIP_MODULE in set(enabled_modules or [])


def reconcile_enabled_modules(enabled_modules, anonymous_requests_enabled) -> bool:
    """The resulting ``anonymous_requests_enabled``. Membership wins."""
    return bool(anonymous_requests_enabled) and not membership_installed(enabled_modules)


def policy_for(enabled_modules, anonymous_requests_enabled) -> str:
    if reconcile_enabled_modules(enabled_modules, anonymous_requests_enabled):
        return ANYONE
    return MEMBERS if membership_installed(enabled_modules) else ACCOUNTS


def effective_policy(makerspace) -> str:
    """Who may submit to this makerspace right now."""
    return policy_for(makerspace.enabled_modules, makerspace.anonymous_requests_enabled)


def anonymous_requests_allowed(makerspace) -> bool:
    """Request-time check. Re-derived rather than trusting the column alone."""
    return effective_policy(makerspace) == ANYONE


class RequestAccessConflict(Exception):
    """Account-less requests were asked for while `membership` is installed."""


def set_anonymous_requests(makerspace, enabled, *, actor=None):
    """Deliberately set the flag under the row lock, and audit the policy change.

    Returns the effective policy AFTER the write. Raises :class:`RequestAccessConflict`
    when asked to open account-less requests on a makerspace that has `membership`
    installed — an explicit operator request is refused loudly rather than silently
    downgraded, which is the opposite of the module-install path (that one forces, because
    the operator was asking about modules, not about this flag).
    """
    from django.db import transaction

    from apps.audit import services as audit
    from apps.makerspaces.models import Makerspace

    with transaction.atomic():
        locked = Makerspace.objects.select_for_update().get(pk=makerspace.pk)
        before = effective_policy(locked)
        wanted = bool(enabled)
        if wanted and membership_installed(locked.enabled_modules):
            raise RequestAccessConflict(
                "The membership module is installed, so borrow requests require an "
                "account. Uninstall `membership` first, or leave account-less requests "
                "off."
            )
        if locked.anonymous_requests_enabled != wanted:
            locked.anonymous_requests_enabled = wanted
            locked.save(update_fields=["anonymous_requests_enabled"])
        after = effective_policy(locked)
        if before != after:
            audit.record(
                actor,
                "makerspace.request_access_changed",
                makerspace=locked,
                target=locked,
                meta={"before": before, "after": after},
            )
    makerspace.refresh_from_db(fields=["anonymous_requests_enabled"])
    return after
