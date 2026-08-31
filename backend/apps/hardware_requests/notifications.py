import logging

from apps.hardware_requests.display import requester_label
from apps.hardware_requests.models import HardwareRequest
from apps.integrations.email_templates import hardware_context, render
from apps.integrations.notify import EmailDelivery, LifecyclePayload, notify_lifecycle
from apps.integrations.staff_notifications import staff_emails_for_feature

logger = logging.getLogger(__name__)


def notify_request_submitted(request):
    return _notify(
        request,
        event="submitted",
        requester_key="request_received",
        staff_event="submitted",
        text_builder=_build_submitted_request_message,
        reply_markup_builder=_submitted_reply_markup,
    )


def notify_request_accepted(request):
    return _notify(
        request,
        event="accepted",
        requester_key="request_accepted",
        staff_event="accepted",
        text_builder=lambda row: f"Hardware request #{row.pk} has been accepted.",
    )


def notify_request_rejected(request):
    return _notify(
        request,
        event="rejected",
        requester_key="request_rejected",
        staff_event="rejected",
        text_builder=lambda row: f"Hardware request #{row.pk} has been rejected.",
    )


def notify_request_issued(request):
    return _notify(
        request,
        event="issued",
        requester_key="request_issued",
        staff_event="issued",
        text_builder=lambda row: f"Hardware request #{row.pk} has been issued.",
    )


def notify_request_returned(request):
    event = (
        request.status
        if request.status in {"partially_returned", "returned", "closed_with_issue"}
        else "returned"
    )
    return _notify(
        request,
        event=event,
        requester_key="request_returned",
        staff_event=event,
        text_builder=lambda row: f"Hardware request #{row.pk} has been returned.",
    )


def notify_return_due(request):
    result = _notify(
        request,
        event="return_reminder",
        requester_key="return_reminder",
        staff_event="return_reminder",
        text_builder=lambda row: f"Hardware request #{row.pk} is due for return.",
        sync=True,
    )
    return bool(result.delivered_counts)


def _notify(
    request,
    *,
    event,
    requester_key,
    staff_event,
    text_builder,
    reply_markup_builder=None,
    sync=False,
):
    logger.info(
        "Hardware request lifecycle notification.",
        extra={
            "request_id": request.pk,
            "makerspace_id": request.makerspace_id,
            "status": request.status,
            "event": event,
        },
    )
    request_id = request.pk

    def build():
        row = (
            HardwareRequest.objects.select_related(
                "makerspace", "requester", "assigned_box"
            )
            .prefetch_related("items__product")
            .get(pk=request_id)
        )
        emails = _email_deliveries(row, requester_key, staff_event)
        markup = reply_markup_builder(row) if reply_markup_builder else None
        return LifecyclePayload(
            text=text_builder(row),
            emails=emails,
            telegram_reply_markup=markup,
        )

    return notify_lifecycle(
        request.makerspace,
        feature="hardware_requests",
        event=event,
        build=build,
        sync=sync,
    )


def _email_deliveries(request, requester_key, staff_event):
    deliveries = []
    if request.requester_contact_email and request.requester_contact_verified:
        # Account-less contact is only a claim made by the submitter. Sending any
        # lifecycle message before verification would turn this endpoint into an
        # email-bomb against arbitrary third parties. Staff delivery remains below.
        rendered = render_email(request, requester_key)
        deliveries.append(
            EmailDelivery(
                to_email=request.requester_contact_email,
                subject=rendered["subject"],
                text_body=rendered["text_body"],
                html_body=rendered["html_body"],
                audience="requester",
                target="requester",
                stream="hardware",
                mute_event=requester_key,
            )
        )
    recipients = staff_emails_for_feature(
        request.makerspace,
        "hardware_requests",
        event=staff_event,
    )
    if recipients:
        rendered = render(
            request.makerspace,
            "hardware",
            "staff",
            staff_event,
            hardware_context(request, staff=True),
        )
        deliveries.extend(
            EmailDelivery(
                to_email=recipient,
                subject=rendered["subject"],
                text_body=rendered["text_body"],
                html_body=rendered["html_body"],
                audience="staff",
                stream="hardware",
                mute_event=staff_event,
            )
            for recipient in recipients
        )
    return tuple(deliveries)


def render_email(request, key):
    return render(
        request.makerspace,
        "hardware",
        "requester",
        key,
        hardware_context(request, staff=False),
    )


def _submitted_reply_markup(request):
    return {
        "inline_keyboard": [
            [
                {"text": "Accept", "callback_data": f"accept:{request.pk}"},
                {
                    "text": "Reject",
                    "callback_data": f"reject:{request.pk}:Rejected from Telegram.",
                },
            ]
        ]
    }


def _build_submitted_request_message(request):
    lines = [
        f"New hardware request #{request.pk}",
        f"Requester: {requester_label(request, fallback='Unknown requester')}",
    ]
    if request.requester_contact_email:
        lines.append(f"Email: {request.requester_contact_email}")
    if request.requester_contact_phone:
        lines.append(f"Phone: {request.requester_contact_phone}")
    if request.requested_for:
        lines.append(f"Requested for: {_clamp(request.requested_for, 300)}")
    items = list(request.items.all())
    if items:
        lines.append("Items:")
        shown = items[:40]
        for item in shown:
            lines.append(f"- {_clamp(item.product.name, 80)}: {item.requested_quantity}")
        if len(items) > len(shown):
            lines.append(f"- ...and {len(items) - len(shown)} more")
    else:
        lines.append("Items: None")
    return _clamp("\n".join(lines), 4000)


def _clamp(text, limit):
    text = str(text)
    return text if len(text) <= limit else text[: limit - 1] + "…"
