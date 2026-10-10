"""Shared fail-safe delivery for F3's small bounded domain snapshots."""

import logging
from functools import wraps

from apps.accounts.models import User
from apps.integrations import recipients
from apps.integrations.email_templates import render
from apps.integrations.email_templates_registry_helpers import bag
from apps.integrations.email_templates_registry_research import REQUESTER_EVENTS
from apps.integrations.notify import EmailDelivery, LifecyclePayload, notify_lifecycle
from apps.integrations.staff_notifications import staff_emails_for_feature
from apps.makerspaces.models import MakerspaceMembership
from apps.makerspaces.servability import is_servable

logger = logging.getLogger(__name__)


def safe_adapter(function):
    """Snapshot failures are fail-safe too, including lazy related-object lookups."""
    @wraps(function)
    def guarded(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except Exception:
            logger.warning("research_notification_snapshot_failed",
                           extra={"adapter": function.__name__})
            return None
    return guarded


def bounded(value, limit=160):
    return str("" if value is None else value)[:limit]


def notify_family(makerspace, feature, event, subject, *, data, scope=None,
                  member_id=None, requester_subject=None, requester_only=False):
    """Queue one edge; resolve fresh gates, recipients and templates after commit.

    subject/requester_subject are immutable bags built by domain adapters. Address
    resolution uses only the event's owner User ID, never a submitted contact field.
    """
    stream = "membership" if feature == "members" else feature

    def build():
        makerspace.refresh_from_db()
        if not is_servable(makerspace) or not recipients.feature_available(makerspace, feature):
            raise ValueError("Notification family is unavailable.")
        context = {"makerspace": bag(name=bounded(makerspace.name)),
                   "event_name": event, "subject": subject}
        staff = render(makerspace, stream, "staff", event, context)
        emails = [EmailDelivery(to_email=email, subject=staff["subject"],
                                text_body=staff["text_body"], html_body=staff["html_body"],
                                stream=stream, audience="staff")
                  for email in ([] if requester_only else staff_emails_for_feature(makerspace, feature, event=event, scope=scope))]
        if member_id and event in REQUESTER_EVENTS.get(stream, ()):
            owner = User.objects.filter(pk=member_id, is_active=True,
                                        access_status=User.AccessStatus.ACTIVE).first()
            membership = MakerspaceMembership.objects.filter(
                makerspace=makerspace, user_id=member_id,
            ).first()
            # Account-only borrowers own debt too; a revoked member is still refused.
            permitted = membership is None or (
                membership.status == "active" and membership.receives_notifications
            )
            if recipients.has_selection(makerspace, feature, event, scope):
                permitted = permitted and recipients.requester_selected(makerspace, feature, event, scope)
            owner_email = (owner.email or "").strip() if owner else ""
            if owner_email and permitted:
                own_context = {**context, "subject": requester_subject or subject}
                own = render(makerspace, stream, "requester", event, own_context)
                emails.append(EmailDelivery(to_email=owner_email, subject=own["subject"],
                                            text_body=own["text_body"], html_body=own["html_body"],
                                            stream=stream, audience="requester"))
        return LifecyclePayload(text=staff["text_body"], context=context, emails=tuple(emails),
                                scope=scope, data=data, staff_channels_enabled=not requester_only)

    try:
        return notify_lifecycle(makerspace, feature=feature, event=event, build=build)
    except Exception:
        logger.warning("research_notification_schedule_failed", extra={
            "makerspace_id": makerspace.pk, "feature": feature, "event": event,
        })
        return None
