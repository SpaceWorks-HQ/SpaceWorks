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
            return User.objects.get(pk=locked_space.anonymous_requester_id)

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
        return user
