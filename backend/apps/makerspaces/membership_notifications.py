"""Email-only member notices plus matrix-controlled membership staff alerts."""

import logging

from apps.integrations.email import send_makerspace_email
from apps.integrations.email_templates import render
from apps.integrations.email_templates_fablab import membership_context
from apps.integrations.notify import EmailDelivery, LifecyclePayload, notify_lifecycle
from apps.integrations.staff_notifications import staff_emails_for_feature
from apps.makerspaces.models import MakerspaceMembership, MembershipRequest

logger = logging.getLogger(__name__)


def _member_email(membership, *, event, subject, body):
    """Queue a direct member email without routing it to staff chat channels."""
    recipient = (membership.user.email or "").strip()
    if not recipient:
        return
    try:
        send_makerspace_email(
            membership.makerspace,
            subject,
            body,
            [recipient],
            stream="membership",
            event=event,
            audience="member",
        )
    except Exception:
        logger.warning(
            "membership_member_email_failed",
            extra={"makerspace_id": membership.makerspace_id, "event": event},
        )


def send_member_welcome(membership, *, source):
    event = "approved" if source == "approval" else "joined"
    _member_email(
        membership,
        event=event,
        subject=f"Welcome to {membership.makerspace.name}",
        body=f"Your membership at {membership.makerspace.name} is active. Welcome!",
    )


def send_member_verified(membership):
    _member_email(
        membership,
        event="verified",
        subject=f"You are verified at {membership.makerspace.name}",
        body=f"You have been verified as a member of {membership.makerspace.name}.",
    )


def _staff_payload(makerspace, event, context):
    # Streams and features differ by name for membership alone (`membership` vs
    # `members`), so the render call spells the stream out rather than reusing the feature.
    staff = render(makerspace, "membership", "staff", event, context)
    emails = tuple(
        EmailDelivery(
            to_email=recipient,
            subject=staff["subject"],
            text_body=staff["text_body"],
            audience="staff",
            stream="membership",
        )
        for recipient in staff_emails_for_feature(makerspace, "members", event=event)
    )
    return LifecyclePayload(
        text=staff["text_body"], emails=emails, context=context
    )


def notify_membership_request_pending(request, *, sync=False):
    request_id = request.pk
    makerspace = request.makerspace

    def build():
        row = MembershipRequest.objects.select_related("makerspace", "user").get(pk=request_id)
        return _staff_payload(
            row.makerspace,
            "request_pending",
            membership_context(row.makerspace, "request_pending", request=row),
        )

    return notify_lifecycle(
        makerspace,
        feature="members",
        event="request_pending",
        build=build,
        sync=sync,
    )


def notify_member_joined(membership, *, sync=False):
    membership_id = membership.pk
    makerspace = membership.makerspace

    def build():
        row = MakerspaceMembership.objects.select_related("makerspace", "user").get(
            pk=membership_id
        )
        return _staff_payload(
            row.makerspace,
            "member_joined",
            membership_context(row.makerspace, "member_joined", user=row.user),
        )

    return notify_lifecycle(
        makerspace,
        feature="members",
        event="member_joined",
        build=build,
        sync=sync,
    )
