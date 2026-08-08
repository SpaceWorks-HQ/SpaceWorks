"""Which rooms a chat alert goes to.

`resolve_destinations` returns a list whose entries are either a `NotificationDestination`
row or **`None`**, and the `None` is the point: it means "send the way this makerspace
sent before destinations existed", i.e. read the credential off the `Makerspace` column.
That single convention is what makes the migration reversible in practice — a space with
no destination rows behaves byte-for-byte as it did, and every sender already has to
handle the makerspace-column path because it is the one that shipped.

Three rules, in the order they are applied:

1. **No destination rows for this channel ⇒ `[None]`.** The legacy column is still the
   truth for that space. The old fields stay readable for a release (D10), so a space
   that configures Slack through the existing settings form after the migration keeps
   working rather than going silent.
2. **A destination with no scope links matches everything** (D11). A room is not a
   permission; an unscoped room is the space's general channel.
3. **A scoped destination matches only a subject it names**, and an alert carrying no
   subject matches no scoped destination at all. Sending un-attributed alerts into a room
   that asked for one machine is the failure this scoping exists to prevent.
"""

import logging

from apps.integrations.models_destinations import NotificationDestination
from apps.integrations.notification_enums import ChatNotificationChannel

logger = logging.getLogger(__name__)


class NotificationScope:
    """The subject an alert is about, as far as destination scoping is concerned.

    A plain container rather than the domain object itself: a maintenance alert knows its
    machine, a stock alert knows its category, and neither should have to know how the
    other is matched. `machine_type` is derived from `machine` when not given, so a caller
    that has a machine gets type-scoped rooms for free — that is the union in D11, not a
    hierarchy.
    """

    __slots__ = ("machine_id", "machine_type_id", "category_id")

    def __init__(self, *, machine=None, machine_type=None, category=None):
        self.machine_id = getattr(machine, "pk", machine)
        self.machine_type_id = getattr(machine_type, "pk", machine_type)
        if self.machine_type_id is None and machine is not None:
            self.machine_type_id = getattr(machine, "machine_type_id", None)
        self.category_id = getattr(category, "pk", category)

    def __bool__(self):
        return any(
            value is not None
            for value in (self.machine_id, self.machine_type_id, self.category_id)
        )


def _matches(destination, scope) -> bool:
    machine_ids = {row.machine_id for row in destination.machine_scopes.all()}
    type_ids = {row.machine_type_id for row in destination.machine_type_scopes.all()}
    category_ids = {row.category_id for row in destination.category_scopes.all()}

    if not (machine_ids or type_ids or category_ids):
        return True
    if scope is None:
        return False
    # Union, not a hierarchy: "all printers plus that one laser" needs no third concept.
    return (
        (scope.machine_id is not None and scope.machine_id in machine_ids)
        or (scope.machine_type_id is not None and scope.machine_type_id in type_ids)
        or (scope.category_id is not None and scope.category_id in category_ids)
    )


def resolve_destinations(makerspace, channel, scope=None):
    """Rooms to post one alert into. `[None]` means the legacy makerspace-column path.

    Fails **open** to `[None]`: a broken destination lookup must fall back to the way the
    space sent yesterday rather than mute it.
    """
    if channel not in ChatNotificationChannel.values:
        return [None]
    try:
        # Deliberately NOT filtered on `is_active` in the query. A space whose only room
        # is deactivated has *chosen* to stop posting there; if the filter happened here,
        # the empty result would read as "this space has no destinations" and fall back to
        # the legacy column, so switching a room off would keep sending.
        rows = list(
            NotificationDestination.objects.filter(
                makerspace=makerspace, channel=channel
            ).prefetch_related("machine_scopes", "machine_type_scopes", "category_scopes")
        )
    except Exception:
        logger.warning(
            "notification_destination_lookup_failed",
            extra={"makerspace_id": getattr(makerspace, "pk", None), "channel": channel},
        )
        return [None]

    if not rows:
        return [None]
    return [row for row in rows if row.is_active and _matches(row, scope)]
