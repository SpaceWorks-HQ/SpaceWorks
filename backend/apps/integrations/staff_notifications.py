import logging

from apps.accounts import rbac
from apps.accounts.models import User
# Aliased: `staff_emails_for_feature` has a local list called `recipients`, and shadowing
# the module makes every reference to it an UnboundLocalError inside that function.
from apps.integrations import notification_rules
from apps.integrations import recipients as recipient_selection
from apps.makerspaces.models import MakerspaceMembership

logger = logging.getLogger(__name__)


_FEATURE_ACTIONS = {
    "hardware_requests": rbac.Action.ACCEPT_REQUEST,
    "printing": rbac.Action.MANAGE_PRINTING,
    "events": rbac.Action.MANAGE_EVENTS,
    "bookings": rbac.Action.MANAGE_BOOKINGS,
    "maintenance": rbac.Action.MANAGE_MACHINES,
    "members": rbac.Action.MANAGE_MAKERSPACE,
}

_FEATURE_STREAMS = {
    "hardware_requests": "hardware",
    "printing": "printing",
}
_STREAM_FEATURES = {value: key for key, value in _FEATURE_STREAMS.items()}


def staff_emails_for_feature(makerspace, feature, event=None) -> list[str]:
    try:
        if not getattr(makerspace, "staff_notifications_enabled", True):
            return []

        # An explicit per-event selection is authoritative once one row exists; with no
        # rows this falls straight through to the action-based resolution below, which is
        # what keeps today's behaviour intact (bookings email is ON by default, so a
        # "default nobody" reading would have silently stopped live booking mail).
        if recipient_selection.has_selection(makerspace, feature, event):
            return recipient_selection.selected_emails(makerspace, feature, event)

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
            MakerspaceMembership.objects.filter(
                makerspace=makerspace,
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
        for membership in memberships:
            if required_action not in rbac.actions_for_membership(membership):
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


def staff_user_ids_for_feature(makerspace, feature, event=None) -> list[int]:
    """Native-push recipients use the same action/mute matrix as staff email."""
    try:
        if not getattr(makerspace, "staff_notifications_enabled", True):
            return []
        # Push is filtered by the same selection as email (D8): it is the mobile form of
        # the member's own message, not a separate audience.
        if recipient_selection.has_selection(makerspace, feature, event):
            return recipient_selection.selected_user_ids(makerspace, feature, event)
        required_action = _FEATURE_ACTIONS.get(feature)
        if required_action is None:
            return []
        stream = _FEATURE_STREAMS.get(feature)
        mutable = bool(stream and event and notification_rules.is_event_mutable(stream, "staff", event))
        memberships = MakerspaceMembership.objects.filter(
            makerspace=makerspace, status="active", receives_notifications=True,
            user__is_active=True, user__access_status=User.AccessStatus.ACTIVE,
        ).exclude(user__is_superuser=True).exclude(
            user__role=User.Role.SUPERADMIN
        ).select_related("assigned_role").order_by("id")
        result = []
        for membership in memberships:
            if required_action not in rbac.actions_for_membership(membership):
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
