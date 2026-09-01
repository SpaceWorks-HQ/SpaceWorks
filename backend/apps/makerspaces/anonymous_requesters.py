"""One inert requester principal per makerspace for account-less loan requests."""

import uuid

from django.db import transaction

from apps.accounts.models import User
from apps.makerspaces.models import Makerspace

SENTINEL_DISPLAY_NAME = "Anonymous requester (system principal)"


def anonymous_requester_ids(makerspace_ids=None):
    """The sentinel user ids, for excluding them from per-PERSON aggregates.

    Every account-less request in a makerspace points at ONE principal, so any report
    that groups by `requester_id` folds every unrelated stranger into a single fictional
    human -- one "repeat offender", one "top borrower". That row is not a person: it
    cannot be contacted, cannot be ranked against real borrowers, and must never be
    restricted (doing so would restrict every future account-less requester at once,
    which is why `accounts.principal_guards.refuse_anonymous_requester_access_mutation`
    exists). Reports exclude these ids instead.

    One query. `makerspace_ids=None` means every makerspace, which is what the
    organization-wide rankings need.
    """
    queryset = Makerspace.objects.exclude(anonymous_requester__isnull=True)
    if makerspace_ids is not None:
        queryset = queryset.filter(pk__in=makerspace_ids)
    return set(queryset.values_list("anonymous_requester_id", flat=True))


def get_or_create_anonymous_requester(makerspace):
    """Return the makerspace's sentinel, creating it under the tenant row lock.

    The makerspace lock is deliberately first, matching membership and walk-in
    creation. Besides serializing two first requests, this keeps the shared lock order
    from turning a concurrent identity operation into a deadlock.
    """
    with transaction.atomic():
        locked_space = Makerspace.objects.select_for_update().get(pk=makerspace.pk)
        if locked_space.anonymous_requester_id is not None:
            existing = User.objects.get(pk=locked_space.anonymous_requester_id)
            # The caller handed us its own instance and will keep using it. Without
            # this the row is created against `locked_space` and the caller's copy
            # still reports `anonymous_requester = None`, which reads as "this space
            # has no principal" at the very moment it just acquired one.
            makerspace.anonymous_requester = existing
            return existing

        # Reuse the existing member_<uuid> allocation namespace. The relationship is
        # the marker; inventing an anonymous_* namespace would contradict the migration
        # contract that reserves walkin_ and member_ for historical identity discovery.
        user = User(
            username=f"member_{uuid.uuid4().hex}",
            display_name=SENTINEL_DISPLAY_NAME,
            email="",
            phone="",
            phone_e164="",
            role=User.Role.REQUESTER,
            is_active=False,
        )
        user.set_unusable_password()
        user.save()

        locked_space.anonymous_requester = user
        locked_space.save(update_fields=["anonymous_requester"])
        # Same reason as above: keep the caller's instance consistent with the row.
        makerspace.anonymous_requester = user
        return user
