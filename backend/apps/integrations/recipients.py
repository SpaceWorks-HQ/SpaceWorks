"""Resolve who receives a (feature, event) notification.

One entry point, two semantics hidden behind it, so no caller has to know which feature
uses which:

* **hardware_requests / printing** keep the existing mute model untouched
  (`EmailNotificationMute`, default-on, uncheck to mute). Not migrated: those are the
  alerts a space cannot afford to lose, and a backfill that got them wrong would fail
  silently.
* **events / bookings / maintenance / members** use explicit per-event selection, where
  **no rows means today's behaviour** — every membership holding the feature's action.
  Rows become authoritative only once one exists.

Everything fails **open** to the action-based default. A broken selection lookup must not
silence a makerspace's alerts; over-notifying is recoverable, missing a maintenance
warning is not. This is deliberately the opposite of the *access* rules, which fail
closed — do not "fix" one to match the other.
"""

import logging

from apps.integrations.models import NotificationFeature
from apps.integrations.models_recipients import (
    NotificationRecipient,
    NotificationRecipientKind,
)

logger = logging.getLogger(__name__)

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
        return list(
            NotificationRecipient.objects.filter(
                makerspace=makerspace, feature=feature, event=event
            ).select_related("role", "user")
        )
    except Exception:
        logger.warning(
            "notification_recipient_lookup_failed",
            extra={"makerspace_id": getattr(makerspace, "pk", None), "feature": feature},
        )
        return []


def has_selection(makerspace, feature, event) -> bool:
    return bool(selection_rows(makerspace, feature, event))


def requester_selected(makerspace, feature, event) -> bool:
    """Whether the subject of the notification was ticked.

    Only meaningful once a selection exists; with no selection the caller's existing
    requester behaviour stands unchanged.
    """
    rows = selection_rows(makerspace, feature, event)
    if not rows:
        return False
    return any(row.kind == NotificationRecipientKind.REQUESTER for row in rows)


def _eligible_memberships(makerspace):
    """Active, notifiable memberships of this makerspace.

    `receives_notifications` is filtered in the QUERY, not in Python: it is the member's
    own opt-out (D5) and it outranks a staff selection, so no branch below can bypass it
    by forgetting the check.
    """
    from apps.accounts.models import User
    from apps.makerspaces.models import MakerspaceMembership

    return (
        MakerspaceMembership.objects.filter(
            makerspace=makerspace,
            status="active",
            receives_notifications=True,
            user__is_active=True,
            user__access_status=User.AccessStatus.ACTIVE,
        )
        .exclude(user__is_superuser=True)
        .exclude(user__role=User.Role.SUPERADMIN)
        .select_related("user", "assigned_role")
        .order_by("id")
    )


def _selected_memberships(makerspace, rows):
    """Memberships matched by a selection, in a stable order.

    Every kind resolves through a MEMBERSHIP of this makerspace — including `user`
    (D4). A notification body carries requester names, machine detail and booking info;
    addressing it to an arbitrary platform account is a hand-operated data leak, and on
    managed hosting it crosses tenants. An external contractor gets a no-action Member
    role first. The role FK is matched by id under a makerspace-scoped queryset, so a
    row pointing at another space's role is inert rather than a leak.
    """
    role_ids = {row.role_id for row in rows if row.role_id}
    user_ids = {row.user_id for row in rows if row.user_id}
    wants_members = any(row.kind == NotificationRecipientKind.MEMBERS for row in rows)
    if not (role_ids or user_ids or wants_members):
        return []

    matched = []
    for membership in _eligible_memberships(makerspace):
        if wants_members:
            matched.append(membership)
        elif membership.assigned_role_id and membership.assigned_role_id in role_ids:
            matched.append(membership)
        elif membership.user_id in user_ids:
            matched.append(membership)
    return matched


def selected_emails(makerspace, feature, event) -> list[str]:
    """Addresses for an explicit selection. Assumes has_selection() is True."""
    rows = selection_rows(makerspace, feature, event)
    if not rows:
        return []
    try:
        emails, seen = [], set()
        for membership in _selected_memberships(makerspace, rows):
            email = (membership.user.email or "").strip()
            if not email:
                continue
            normalized = email.lower()
            if normalized in seen:
                continue
            seen.add(normalized)
            emails.append(email)
        return emails
    except Exception:
        logger.warning(
            "notification_selected_recipient_resolution_failed",
            extra={"makerspace_id": getattr(makerspace, "pk", None), "feature": feature},
            exc_info=True,
        )
        return []


def selected_user_ids(makerspace, feature, event) -> list[int]:
    """Push recipients for an explicit selection.

    Native push is a MEMBER channel as well as a staff one (D8) — the mobile form of the
    member's own email — so it is filtered by exactly the same selection and opt-out as
    email rather than by a separate matrix.
    """
    rows = selection_rows(makerspace, feature, event)
    if not rows:
        return []
    try:
        return list(
            dict.fromkeys(
                membership.user_id
                for membership in _selected_memberships(makerspace, rows)
            )
        )
    except Exception:
        logger.warning(
            "notification_selected_push_resolution_failed",
            extra={"makerspace_id": getattr(makerspace, "pk", None), "feature": feature},
            exc_info=True,
        )
        return []
