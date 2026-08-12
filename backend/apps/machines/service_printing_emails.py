"""Printing-branded lifecycle delivery for kernel 3D-printer requests."""

import logging
from types import SimpleNamespace

from django.conf import settings

from apps.integrations.email_templates import printing_context, render
from apps.integrations.notify import EmailDelivery, LifecyclePayload, notify_lifecycle
from apps.integrations.staff_notifications import staff_emails_for_feature
from apps.machines.printer_capabilities import is_printer_type

logger = logging.getLogger(__name__)
REQUESTER_EVENTS = frozenset({"submitted", "accepted", "started", "rejected", "completed"})


def _request_machine_type(request):
    return request.queue.machine_type if request.queue_id else request.bucket.machine.machine_type


def _is_printer_request(request):
    return is_printer_type(_request_machine_type(request))


def _projection(request):
    payload = request.capability_payload or {}
    status = "printing" if request.status == request.Status.IN_PROGRESS else request.status
    makerspace = request.makerspace
    queue_name = request.queue.name if request.queue_id else request.bucket.name
    return SimpleNamespace(
        id=request.pk, status=status, title=request.title, reason=request.reason,
        material=payload.get("requested_material", ""), color=payload.get("requested_color", ""),
        quantity=payload.get("quantity", 1), requester_name=request.requester_name,
        contact_email=request.contact_email, contact_phone=request.contact_phone,
        reprint_of_id=request.reprint_of_id, requester=request.requester,
        bucket=SimpleNamespace(name=queue_name, makerspace=makerspace),
    )


def _requester_render(event, request):
    recipient = request.contact_email or request.requester.email
    if not recipient:
        return None, None
    base = getattr(settings, "PUBLIC_APP_BASE_URL", "") or ""
    status_url = f"{base}/m/{request.makerspace.slug}/print?token={request.public_token}" if base else ""
    row = _projection(request)
    return recipient, render(
        request.makerspace,
        "printing",
        "requester",
        event,
        printing_context(row, status_url, request.public_token),
        machine_type=_request_machine_type(request),
    )


def _staff_render(event, request):
    return render(
        request.makerspace,
        "printing",
        "staff",
        event,
        printing_context(_projection(request), "", ""),
        machine_type=_request_machine_type(request),
    )


def _staff_body(event, request):
    row = _projection(request)
    lines = [
        f"Print request #{row.id} {event}.", "", f"Status: {row.status}",
        f"Title: {row.title}", f"Requester: {row.requester_name or row.requester.username}",
    ]
    if row.contact_email or row.requester.email:
        lines.append(f"Email: {row.contact_email or row.requester.email}")
    if row.contact_phone:
        lines.append(f"Phone: {row.contact_phone}")
    if row.material:
        lines.append(f"Material: {row.material}")
    if row.color:
        lines.append(f"Color: {row.color}")
    lines.append(f"Quantity: {row.quantity}")
    if row.reason:
        lines.append(f"Reason: {row.reason}")
    return "\n".join(lines)


def notify_printer_service_status(request, event, *, sync=False):
    """Use the established printing template and mute matrix for kernel work."""
    if not _is_printer_request(request):
        return None
    makerspace = request.makerspace
    request_id = request.pk

    def build():
        from apps.machines.models import MachineServiceRequest
        row = MachineServiceRequest.objects.select_related(
            "makerspace", "requester", "queue__machine_type", "bucket__machine__machine_type"
        ).get(pk=request_id)
        emails = []
        if event in REQUESTER_EVENTS:
            recipient, rendered = _requester_render(event, row)
            if recipient:
                emails.append(EmailDelivery(
                    to_email=recipient, subject=rendered["subject"], text_body=rendered["text_body"],
                    html_body=rendered["html_body"], audience="requester", target="requester",
                    stream="printing", mute_event=event,
                ))
        recipients = staff_emails_for_feature(makerspace, "printing", event=event)
        if recipients:
            rendered = _staff_render(event, row)
            emails.extend(EmailDelivery(
                to_email=recipient, subject=rendered["subject"], text_body=rendered["text_body"],
                html_body=rendered["html_body"], audience="staff", stream="printing", mute_event=event,
            ) for recipient in recipients)
        return LifecyclePayload(text=_staff_body(event, row), emails=tuple(emails))

    try:
        return notify_lifecycle(makerspace, feature="printing", event=event, build=build, sync=sync)
    except Exception:
        logger.exception("machine_printer_email_send_failed", extra={"event": event, "request_id": request_id})
        return None
