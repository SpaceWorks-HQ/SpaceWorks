"""One inert requester principal per makerspace for account-less loan requests."""

import uuid

from django.db import transaction

from apps.accounts.models import User
from apps.makerspaces.models import Makerspace

SENTINEL_DISPLAY_NAME = "Anonymous requester (system principal)"


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
