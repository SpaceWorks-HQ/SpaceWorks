"""Matrix fan-out addressed by User identity, never free-text contact ownership."""

import logging
from dataclasses import dataclass

from django.db import transaction

from apps.accounts import rbac
from apps.accounts.models import User
from apps.integrations.staff_notifications import staff_user_ids_for_feature
from apps.makerspaces.models import MakerspaceMembership
from apps.makerspaces.platform import feature_enabled, module_enabled
from apps.notifications.models_inbox import NotificationInboxRow
from apps.notifications.preferences import personal_enabled

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class InboxDelivery:
    user_id: int
    title: str
    summary: str
    link: str = ""


def eligible_owner(makerspace, user_id):
    """Explicit domain owners may be account-only borrowers; revoked members cannot read."""
    if not user_id or not User.objects.filter(
        pk=user_id, is_active=True, access_status=User.AccessStatus.ACTIVE,
        is_tenant_dump_stub=False,
    ).exists():
        return False
    membership = rbac.scope_notification_policy(
        MakerspaceMembership.objects.all(), makerspace_id=makerspace.pk,
    ).filter(user_id=user_id).first()
    return membership is None or (membership.status == "active" and membership.receives_notifications)


def safe_link(value):
    # Only local application paths; never a javascript URL, external origin or token URL.
    return value[:300] if (value.startswith("/") and not value.startswith("//")
                          and "\\" not in value and not any(ord(char) < 32 or ord(char) == 127 for char in value)) else ""


def write_matrix_inbox(makerspace, feature, event, payload, event_key):
    from apps.tenant_migration.gate_runtime import tenant_write

    with tenant_write(makerspace.pk):
        makerspace.refresh_from_db()
        _write_matrix_inbox(makerspace, feature, event, payload, event_key)


def _write_matrix_inbox(makerspace, feature, event, payload, event_key):
    from apps.integrations.recipients import feature_available
    from apps.makerspaces.servability import is_servable

    if not is_servable(makerspace) or not module_enabled(makerspace, "notifications") or not feature_available(makerspace, feature):
        return
    recipients = {}
    if payload.staff_channels_enabled:
        for user_id in staff_user_ids_for_feature(makerspace, feature, event, payload.scope):
            recipients[user_id] = InboxDelivery(
                user_id, f"{feature.replace('_', ' ').title()}: {event.replace('_', ' ')}",
                payload.text, f"/m/{makerspace.slug}/admin/notifications",
            )
    if feature_enabled(makerspace, "notifications.member_inbox"):
        from apps.integrations import recipients as selection

        # Mail is a fallback; an adapter's deliberately bounded inbox summary wins.
        own = [InboxDelivery(
            mail.user_id, mail.subject, mail.text_body,
            f"/m/{makerspace.slug}/member",
        ) for mail in payload.emails if mail.user_id and mail.audience in {"requester", "member"}]
        own.extend(payload.inbox)
        if selection.has_selection(makerspace, feature, event, payload.scope) and not selection.requester_selected(
            makerspace, feature, event, payload.scope,
        ):
            own = []
        for delivery in own:
            if eligible_owner(makerspace, delivery.user_id):
                # Requester wording wins when an owner is also staff.
                recipients[delivery.user_id] = delivery
    for user_id, delivery in recipients.items():
        if not personal_enabled(makerspace, user_id, feature, "in_app", event=event):
            continue
        with transaction.atomic():
            row, created = rbac.scope_notification_policy(
                NotificationInboxRow.objects.all(), makerspace_id=makerspace.pk,
            ).get_or_create(
                makerspace=makerspace, user_id=user_id, event_key=event_key,
                defaults={"feature": feature, "event": event, "title": delivery.title[:200],
                          "summary": delivery.summary[:12000], "link": safe_link(delivery.link)},
            )
            if created:
                transaction.on_commit(lambda uid=user_id: _hint(makerspace.pk, uid), robust=True)


def _hint(makerspace_id, user_id):
    from apps.operations.live import _payload, publish, user_channel

    publish(user_channel(user_id), _payload("notification.created", makerspace_id, "", "", None))
