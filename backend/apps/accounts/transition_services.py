"""The sole authorised transition from a walk-in person record to an account."""

from collections.abc import Callable
from datetime import datetime

from django.db import connection, transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.accounts.services_tokens import blacklist_outstanding_tokens
from apps.audit import services as audit

RevocationHook = Callable[[User, datetime], None]
CredentialWriter = Callable[[User], None]
_REVOCATION_HOOKS: dict[str, RevocationHook] = {}


class WalkInTransitionError(Exception):
    pass


def register_walk_in_revocation_hook(name: str, hook: RevocationHook) -> None:
    """Register claim-state revocation performed inside the transition transaction.

    The claim module must register one hook that revokes every unconsumed claim code,
    every live claim session, and every active presence row created through those claim
    sessions. The hook receives the locked user and transition timestamp, performs only
    database work, and must raise on incomplete revocation so the whole transition rolls
    back. It must not perform network, email, object-storage, or other external I/O while
    the user row lock is held.
    """
    if not name or not callable(hook):
        raise ValueError("A named callable revocation hook is required.")
    existing = _REVOCATION_HOOKS.get(name)
    if existing is not None and existing is not hook:
        raise RuntimeError(f"Walk-in revocation hook {name!r} is already registered.")
    _REVOCATION_HOOKS[name] = hook


def unregister_walk_in_revocation_hook(name: str) -> None:
    """Remove a hook during application teardown or isolated tests."""
    _REVOCATION_HOOKS.pop(name, None)


def transition_walk_in_to_account(
    user: User,
    *,
    actor: User | None,
    credential_writer: CredentialWriter | None = None,
) -> User:
    """Atomically transition ``user`` and revoke every pre-transition bearer.

    This is the only caller allowed to set the database GUC. Under the user row lock it
    clears the marker; invokes the claim hook contract (unconsumed codes, live sessions,
    and active claim-created presence); blacklists all SimpleJWT ``OutstandingToken``
    rows; revokes device grants and their refresh families; optionally performs a local
    credential write; and audits the transition. ``credential_writer`` exists for
    credential-creation surfaces such as Django admin and must perform database work
    only. Any failure rolls every part back together.
    """
    hooks = tuple(_REVOCATION_HOOKS.values())
    with transaction.atomic():
        locked = User.objects.select_for_update().get(pk=user.pk)
        if not locked.is_walk_in:
            raise WalkInTransitionError("This user is not a walk-in record.")

        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL app.allow_walk_in_transition = 'on'")

        locked.is_walk_in = False
        locked.save(update_fields=["is_walk_in"])
        transitioned_at = timezone.now()
        for hook in hooks:
            hook(locked, transitioned_at)

        blacklist_outstanding_tokens(locked)
        if credential_writer is not None:
            credential_writer(locked)

        audit.record(actor, "member.walk_in_transitioned", target=locked)
        return locked
