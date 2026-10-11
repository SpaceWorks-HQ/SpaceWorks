"""Borrower-only delivery and F3 staff escalation through the existing matrix."""

from datetime import timezone as datetime_timezone

from apps.integrations.email_templates import hardware_context, render
from apps.integrations.email_templates_registry import bag
from django.utils import timezone
from django.utils.html import escape
from apps.integrations.notify import EmailDelivery, LifecyclePayload, notify_lifecycle
from apps.integrations.staff_notifications import staff_emails_for_feature


def deliver_loan_reminder(makerspace, loan, reminder, message, local_tz):
    def build():
        context = hardware_context(loan, staff=reminder.kind == "escalation")
        values = {key: value for key, value in vars(context["request"]).items() if key != "_frozen"}
        # Preserve the documented datetime type for existing editable date filters.
        due = loan.return_due_at.astimezone(local_tz)
        # Django omits T/O at an ambiguous ZoneInfo wall time. The UTC instant has
        # already selected the fold, so retain its resolved offset and zone label.
        values["return_due_at"] = due.replace(tzinfo=datetime_timezone(due.utcoffset(), due.tzname()))
        context["now"] = timezone.now().astimezone(local_tz)
        context["request"] = bag(**values)
        if reminder.kind == "escalation":
            context["staff_summary"] = message.body
        staff = reminder.kind == "escalation"
        audience = "staff" if staff else "requester"
        with timezone.override(local_tz):
            rendered = render(makerspace, "hardware", audience, "return_reminder", context, use_tz=False)
        if not staff:
            # Include the zone/UTC offset explicitly even when a custom template's
            # date format omits it, especially for an ambiguous DST due time.
            rendered["text_body"] += "\n\n" + message.body
            rendered["html_body"] += f"<p>{escape(message.body)}</p>"
        if staff:
            addresses = staff_emails_for_feature(makerspace, "hardware_requests", event="overdue_escalated")
        else:
            borrower = loan.requester
            # Use the borrower's own verified address, never a recipient chosen by staff
            # or an unverified account-less contact claim.
            proven = borrower.email_verified_at or (
                loan.requester_contact_verified and borrower.email == loan.requester_contact_email
            )
            addresses = [borrower.email] if borrower.email and proven else []
        deliveries = tuple(EmailDelivery(
            to_email=address, subject=rendered["subject"], text_body=rendered["text_body"],
            html_body=rendered["html_body"], audience=audience,
            target="" if staff else "requester", stream="hardware", mute_event="return_reminder",
        ) for address in addresses)
        return LifecyclePayload(text=message.body, emails=deliveries, data={"request_id": loan.pk},
                                staff_channels_enabled=staff)

    return notify_lifecycle(
        makerspace, feature="hardware_requests",
        event="overdue_escalated" if reminder.kind == "escalation" else "return_reminder",
        build=build, sync=True,
    )
