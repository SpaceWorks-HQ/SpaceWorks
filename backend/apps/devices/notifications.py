"""Credential-free state snapshots delivered through the staff lifecycle fan-out."""

import logging

from apps.integrations.email_templates import render
from apps.integrations.email_templates_registry_helpers import bag
from apps.integrations.notify import EmailDelivery, LifecyclePayload, notify_lifecycle
from apps.integrations.staff_notifications import staff_emails_for_feature
from apps.makerspaces.platform import module_enabled
from apps.makerspaces.servability import is_servable


logger = logging.getLogger(__name__)


def notify_device_state(makerspace, device, event, *, now):
    # Capture the edge now: a recovery before on_commit must not rewrite an outage.
    context = {
        "device": bag(id=str(device.pk), name=device.name, kind=device.kind,
                      state=event, last_seen_at=device.last_seen_at,
                      offline_since=device.offline_since),
        "now": now,
    }

    def build():
        # Disable/archive between the mutation and delivery suppresses the alert.
        makerspace.refresh_from_db()
        if not is_servable(makerspace) or not module_enabled(makerspace, "devices"):
            raise ValueError("Device notifications are unavailable.")
        staff = render(makerspace, "devices", "staff", event, context)
        emails = tuple(
            EmailDelivery(to_email=email, subject=staff["subject"],
                          text_body=staff["text_body"], html_body=staff["html_body"],
                          stream="devices", audience="staff")
            for email in staff_emails_for_feature(makerspace, "devices", event=event)
        )
        return LifecyclePayload(text=staff["text_body"], emails=emails, context=context)

    try:
        return notify_lifecycle(makerspace, feature="devices", event=event, build=build)
    except Exception:
        logger.warning("device_notification_schedule_failed", extra={
            "makerspace_id": makerspace.pk, "device_id": str(device.pk), "event": event,
        })
        return None
