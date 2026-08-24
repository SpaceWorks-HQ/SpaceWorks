"""Resolve who receives a (feature, event) notification.

One entry point, two semantics hidden behind it, so no caller has to know which feature
uses which:

* **hardware_requests / printing** keep the existing mute model untouched
  (`EmailNotificationMute`, default-on, uncheck to mute). Not migrated: those are the
  alerts a space cannot afford to lose, and a backfill that got them wrong would fail
  silently.
* **events / bookings / maintenance / members** use explicit per-event selection. A row
  becomes authoritative only when it covers the alert subject; otherwise today's
  action-based recipient default applies.

Everything fails **open** to the action-based default. A broken selection lookup must not
silence a makerspace's alerts; over-notifying is recoverable, missing a maintenance
warning is not. This is deliberately the opposite of the *access* rules, which fail
closed — do not "fix" one to match the other.
"""

import logging

from apps.integrations.models import NotificationFeature
from apps.integrations.models_recipients import NotificationRecipientKind
from apps.integrations.recipient_scope_matching import rule_covers as _rule_covers

logger = logging.getLogger("apps.integrations.recipients")

# Features whose recipients can be picked per event. The other two are mute-based.
SELECTABLE_FEATURES = frozenset(
    {
        NotificationFeature.EVENTS,
        NotificationFeature.BOOKINGS,
        NotificationFeature.MAINTENANCE,
        NotificationFeature.MEMBERS,
    }
)

# The module that must be installed for a feature's notifications to exist at all. A space
# running inventory and machines but no events must not be offered event recipients, and
# must not resolve any if stale rows exist. `hardware_requests` maps to a core module, so
# it is always present.
FEATURE_MODULES = {
    NotificationFeature.HARDWARE_REQUESTS: "request_workflow",
    NotificationFeature.PRINTING: "printing",
    NotificationFeature.EVENTS: "events",
    NotificationFeature.BOOKINGS: "bookings",
    NotificationFeature.MAINTENANCE: "maintenance",
    NotificationFeature.MEMBERS: "membership",
}


def feature_available(makerspace, feature) -> bool:
    """False when the feature's module is not installed for this makerspace."""
    key = FEATURE_MODULES.get(feature)
    if key is None or makerspace is None:
        return True
    try:
        from apps.makerspaces.platform import module_enabled

        return bool(module_enabled(makerspace, key))
    except Exception:
        # Fail open, as everywhere else here: a capability lookup failure must not mute a
        # space. A genuinely uninstalled module has no domain objects to notify about
        # anyway, so the practical risk of this default is near zero.
        logger.warning(
            "notification_feature_module_check_failed",
            extra={"makerspace_id": getattr(makerspace, "pk", None), "feature": feature},
        )
        return True


def selection_rows(makerspace, feature, event):
    """Selected recipients for one (feature, event), or [] when none are selected.

    The module gate lives HERE rather than in front of the whole resolver (D14): stale
    rows for an uninstalled module resolve to nothing, and the caller falls back to the
    action-based default. Gating the resolver instead would mute a space on a capability
    change, which is the one outcome D15 forbids.
    """
    if feature not in SELECTABLE_FEATURES or not event:
        return []
    if not feature_available(makerspace, feature):
        return []
    try:
        from apps.integrations import recipients

        return list(
            recipients.NotificationRecipient.objects.filter(
                makerspace=makerspace, feature=feature, event=event
            )
            .select_related("role", "user")
            .prefetch_related("machine_scopes", "machine_type_scopes", "category_scopes")
        )
    except Exception:
        logger.warning(
            "notification_recipient_lookup_failed",
            extra={"makerspace_id": getattr(makerspace, "pk", None), "feature": feature},
        )
        return []


def has_selection(makerspace, feature, event, scope=None) -> bool:
    """Whether an explicit selection is authoritative for this alert subject.

    A row narrowed to lasers says nothing about a printer alert. Treating its mere
    existence as authoritative would make ``selected_*`` return nobody and silently
    suppress the printer warning. A selection takes over only when at least one row
    covers the subject; otherwise callers retain the action-based default.
    """
    try:
        return any(
            _rule_covers(row, scope)
            for row in selection_rows(makerspace, feature, event)
        )
    except Exception:
        logger.warning(
            "notification_recipient_coverage_check_failed",
            extra={"makerspace_id": getattr(makerspace, "pk", None), "feature": feature},
            exc_info=True,
        )
        return False


def requester_selected(makerspace, feature, event, scope=None) -> bool:
    """Whether the subject of the notification was ticked.

    Only meaningful once a selection exists; with no selection the caller's existing
    requester behaviour stands unchanged.

    Scoped exactly like :func:`has_selection`: a requester row narrowed to the lasers says
    nothing about a printer alert, and reading its bare existence as "ticked" made a
    delegated laser rule speak for every other team's subjects. Rows that do not cover the
    subject are ignored rather than answered, so an uncovered alert falls back to the
    caller's own requester behaviour instead of inheriting someone else's narrowing.
    """
    try:
        return any(
            row.kind == NotificationRecipientKind.REQUESTER and _rule_covers(row, scope)
            for row in selection_rows(makerspace, feature, event)
        )
    except Exception:
        # Fails OPEN to the caller's existing behaviour, matching every other capability
        # lookup here: a broken coverage check must never silently mute an alert.
        logger.warning(
            "notification_requester_coverage_check_failed",
            extra={"makerspace_id": getattr(makerspace, "pk", None), "feature": feature},
            exc_info=True,
        )
        return False
