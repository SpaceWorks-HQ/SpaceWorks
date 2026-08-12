import logging

from django.template import Context, Template
from django.utils import timezone

from apps.integrations.email_templates_registry import bag, get_entry
from apps.integrations.models import EmailTemplate, MachineTypeEmailTemplate

logger = logging.getLogger(__name__)


def _makerspace_bag(makerspace):
    return bag(
        name=makerspace.name,
        location=makerspace.location,
        map_url=makerspace.map_url,
    )


def hardware_context(request, *, staff):
    makerspace = _makerspace_bag(request.makerspace)
    request_items = None
    if "items" in getattr(request, "_prefetched_objects_cache", {}):
        prefetched_items = list(request.items.all())
        if all("product" in item._state.fields_cache for item in prefetched_items):
            request_items = prefetched_items
    if request_items is None:
        request_items = list(request.items.select_related("product"))
    items = [
        bag(
            product=bag(name=item.product.name),
            requested_quantity=item.requested_quantity,
            issued_quantity=item.issued_quantity,
        )
        for item in request_items
    ]
    assigned_box = None
    if request.assigned_box_id:
        assigned_box = bag(code=request.assigned_box.code)
    request_bag = bag(
        id=request.id,
        status=request.status,
        return_due_at=request.return_due_at,
        rejection_reason=request.rejection_reason,
        requester_name=request.requester_name,
        requester_username=request.requester_username,
        requester_contact_email=request.requester_contact_email,
        requester_contact_phone=request.requester_contact_phone,
        requested_for=request.requested_for,
        assigned_box=assigned_box,
        items=items,
        makerspace=makerspace,
    )
    context = {
        "request": request_bag,
        "items": items,
        "makerspace": makerspace,
        "now": timezone.now(),
    }
    if staff:
        from apps.hardware_requests.staff_notifications import _staff_summary

        context["staff_summary"] = _staff_summary(request)
    return context


def printing_context(print_request, status_url, public_token):
    makerspace = _makerspace_bag(print_request.bucket.makerspace)
    print_request_bag = bag(
        id=print_request.id,
        status=print_request.status,
        title=print_request.title,
        reason=print_request.reason,
        material=print_request.material,
        color=print_request.color,
        quantity=print_request.quantity,
        requester_name=print_request.requester_name,
        contact_email=print_request.contact_email,
        contact_phone=print_request.contact_phone,
        reprint_of_id=print_request.reprint_of_id,
        requester=bag(
            username=print_request.requester.username,
            email=print_request.requester.email,
        ),
        bucket=bag(name=print_request.bucket.name, makerspace=makerspace),
    )
    return {
        "print_request": print_request_bag,
        "makerspace": makerspace,
        "status_url": status_url,
        "public_token": str(public_token),
        "now": timezone.now(),
    }


def render(makerspace, stream, audience, key, context, *, machine_type=None):
    # is_active=False means "use the built-in default for this event" (the original
    # HardwareEmailTemplate semantic), NOT "suppress the email" — lifecycle notifications
    # always send, so a toggled-off custom row falls through to the registry default below.
    if machine_type is not None:
        override = MachineTypeEmailTemplate.objects.filter(
            makerspace=makerspace,
            machine_type=machine_type,
            stream=stream,
            audience=audience,
            key=key,
            is_active=True,
        ).first()
        if override is not None:
            try:
                return _render_strings(
                    override.subject,
                    override.text_body,
                    override.html_body,
                    context,
                )
            except Exception:
                logger.warning(
                    "email_template_render_failed",
                    extra={
                        "makerspace_id": makerspace.pk,
                        "machine_type_id": machine_type.pk,
                        "stream": stream,
                        "audience": audience,
                        "key": key,
                    },
                    exc_info=True,
                )

    row = EmailTemplate.objects.filter(
        makerspace=makerspace,
        stream=stream,
        audience=audience,
        key=key,
        is_active=True,
    ).first()
    entry = get_entry(stream, audience, key)
    if entry is None:
        raise KeyError(f"Unknown email template: {stream}/{audience}/{key}")

    if row is not None:
        try:
            return _render_strings(row.subject, row.text_body, row.html_body, context)
        except Exception:
            logger.warning(
                "email_template_render_failed",
                extra={
                    "makerspace_id": makerspace.pk,
                    "stream": stream,
                    "audience": audience,
                    "key": key,
                },
                exc_info=True,
            )

    return _render_strings(
        entry.default_subject,
        entry.default_text,
        entry.default_html,
        context,
    )


def render_preview(stream, audience, key, subject, text_body, html_body):
    entry = get_entry(stream, audience, key)
    if entry is None:
        raise KeyError(f"Unknown email template: {stream}/{audience}/{key}")
    return _render_strings(subject, text_body, html_body, entry.sample_context)


def _render_strings(subject, text_body, html_body, context):
    return {
        "subject": _render_string(subject, context).strip(),
        "text_body": _render_string(text_body, context),
        "html_body": _render_string(html_body, context) if html_body else "",
    }


def _render_string(value, context):
    return Template(value or "").render(Context(context, autoescape=True))
