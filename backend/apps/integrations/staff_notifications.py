import logging

from apps.accounts import rbac
from apps.accounts.models import User
# Aliased: `staff_emails_for_feature` has a local list called `recipients`, and shadowing
# the module makes every reference to it an UnboundLocalError inside that function.
from apps.integrations import notification_rules
from apps.integrations import recipients as recipient_selection
from apps.makerspaces.models import MakerspaceMembership
from .notifications_machine_scope import reminder_memberships

logger = logging.getLogger(__name__)


_FEATURE_ACTIONS = {
    "hardware_requests": rbac.Action.ACCEPT_REQUEST,
    "printing": rbac.Action.MANAGE_PRINTING,
    "events": rbac.Action.MANAGE_EVENTS,
    "bookings": rbac.Action.MANAGE_BOOKINGS,
    "maintenance": rbac.Action.MANAGE_MACHINES,
    "members": rbac.Action.MANAGE_MEMBERS,
    "api_access": rbac.Action.MANAGE_MAKERSPACE,
    "devices": rbac.Action.MANAGE_DEVICES,
    # Match the ledger read authority, including delegated finance roles.
    "payments": rbac.Action.VIEW_FINANCE,
    "stock": (rbac.Action.EDIT_INVENTORY, rbac.Action.MANAGE_PRINTING),
    "certifications": rbac.Action.MANAGE_MACHINES,
}

_FEATURE_STREAMS = {
    "hardware_requests": "hardware",
    "printing": "printing",
    "devices": "devices",
}
_STREAM_FEATURES = {value: key for key, value in _FEATURE_STREAMS.items()}


def _holds_feature_action(membership, required_action):
    required = required_action if isinstance(required_action, tuple) else (required_action,)
    return bool(set(required) & set(rbac.actions_for_membership(membership)))


def _staff_emails_for_feature(makerspace, feature, event=None, scope=None) -> list[str]:
    try:
        if not getattr(makerspace, "staff_notifications_enabled", True):
            return []

        # An explicit per-event selection is authoritative once one row covers this
        # alert's subject; otherwise this falls through to action-based resolution, which is
        # what keeps today's behaviour intact (bookings email is ON by default, so a
        # "default nobody" reading would have silently stopped live booking mail).
        if recipient_selection.has_selection(makerspace, feature, event, scope):
            return recipient_selection.selected_emails(
                makerspace, feature, event, scope
            )

        required_action = _FEATURE_ACTIONS.get(feature)
        if required_action is None:
            logger.warning(
                "staff_notification_unknown_feature",
                extra={
                    "makerspace_id": getattr(makerspace, "pk", None),
                    "feature": feature,
                },
            )
            return []

        stream = _FEATURE_STREAMS.get(feature)
        mutable_event = bool(
            stream
            and event
            and notification_rules.is_event_mutable(stream, "staff", event)
        )

        memberships = (
            reminder_memberships(MakerspaceMembership.objects.all(), makerspace, feature, event).filter(
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

        seen = set()
        recipients = []
        # The fallback predates machine scoping and is makerspace-wide, so an alert naming
        # a machine must not mail a maintainer whose role cannot reach it.
        admits = recipient_selection.reach_filter_for(memberships, scope)
        for membership in memberships:
            if not _holds_feature_action(membership, required_action):
                continue
            if not admits(membership):
                continue
            if mutable_event and notification_rules.role_muted(
                makerspace, stream, event, membership.role
            ):
                continue
            email = (membership.user.email or "").strip()
            if not email:
                continue
            normalized = email.lower()
            if normalized in seen:
                continue
            seen.add(normalized)
            recipients.append(email)
        return recipients
    except Exception:
        logger.warning(
            "staff_notification_recipient_resolution_failed",
            extra={
                "makerspace_id": getattr(makerspace, "pk", None),
                "feature": feature,
            },
            exc_info=True,
        )
        return []


def staff_emails_for_stream(makerspace, stream, event=None) -> list[str]:
    feature = _STREAM_FEATURES.get(stream)
    if feature is None:
        logger.warning(
            "staff_notification_unknown_stream",
            extra={
                "makerspace_id": getattr(makerspace, "pk", None),
                "stream": stream,
            },
        )
        return []
    return staff_emails_for_feature(makerspace, feature, event=event)


def _staff_user_ids_for_feature(makerspace, feature, event=None, scope=None) -> list[int]:
    """Native-push recipients use the same action/mute matrix as staff email."""
    try:
        if not getattr(makerspace, "staff_notifications_enabled", True):
            return []
        # Push is filtered by the same selection as email (D8): it is the mobile form of
        # the member's own message, not a separate audience.
        if recipient_selection.has_selection(makerspace, feature, event, scope):
            return recipient_selection.selected_user_ids(
                makerspace, feature, event, scope
            )
        required_action = _FEATURE_ACTIONS.get(feature)
        if required_action is None:
            return []
        stream = _FEATURE_STREAMS.get(feature)
        mutable = bool(stream and event and notification_rules.is_event_mutable(stream, "staff", event))
        memberships = reminder_memberships(MakerspaceMembership.objects.all(), makerspace, feature, event).filter(
            makerspace=makerspace, status="active", receives_notifications=True,
            user__is_active=True, user__access_status=User.AccessStatus.ACTIVE,
        ).exclude(user__is_superuser=True).exclude(
            user__role=User.Role.SUPERADMIN
        ).select_related("assigned_role").order_by("id")
        result = []
        admits = recipient_selection.reach_filter_for(memberships, scope)
        for membership in memberships:
            if not _holds_feature_action(membership, required_action):
                continue
            if not admits(membership):
                continue
            if mutable and notification_rules.role_muted(
                makerspace, stream, event, membership.role
            ):
                continue
            result.append(membership.user_id)
        return list(dict.fromkeys(result))
    except Exception:
        logger.warning("push_recipient_resolution_failed", extra={
            "makerspace_id": getattr(makerspace, "pk", None), "feature": feature,
        })
        return []


def staff_emails_for_feature(makerspace, feature, event=None, scope=None):
    from .notifications_machine_scope import filter_reminder_emails
    try:
        return filter_reminder_emails(makerspace, feature, event, scope,
                                     _staff_emails_for_feature(makerspace, feature, event, scope))
    except Exception:
        logger.warning("reminder_recipient_resolution_failed", extra={"feature": feature})
        return []


def staff_user_ids_for_feature(makerspace, feature, event=None, scope=None):
    from .notifications_machine_scope import reminder_staff_ids
    try:
        ids = _staff_user_ids_for_feature(makerspace, feature, event, scope)
        allowed = reminder_staff_ids(makerspace, feature, event, scope)
        return ids if allowed is None else [pk for pk in ids if pk in allowed]
    except Exception:
        logger.warning("reminder_push_recipient_resolution_failed", extra={"feature": feature})
        return []
