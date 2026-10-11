from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import NotFound, ValidationError

from apps.events.invites import require_feature
from apps.events.models import EventTicketType
from apps.events.registration_access import has_active_event_membership
from apps.makerspaces.platform import feature_enabled


def available_ticket_types(event, user=None):
    if not feature_enabled(event.makerspace, "events.ticket_types"):
        return event.ticket_types.none()
    now = timezone.now()
    from django.db.models import Q

    rows = event.ticket_types.filter(makerspace_id=event.makerspace_id, is_active=True).filter(
        Q(sales_start_at__isnull=True) | Q(sales_start_at__lte=now),
        Q(sales_end_at__isnull=True) | Q(sales_end_at__gt=now),
    )
    if not has_active_event_membership(user, event.makerspace):
        rows = rows.filter(audience=EventTicketType.Audience.PUBLIC)
    return rows


def ticket_selection_required(event):
    return feature_enabled(event.makerspace, "events.ticket_types") and event.ticket_types.filter(is_active=True).exists()


def select_ticket(event, ticket_type_id, member):
    if ticket_type_id is None:
        if ticket_selection_required(event):
            raise ValidationError({"ticket_type_id": "Choose an available ticket type."})
        return None
    require_feature(event, "events.ticket_types")
    ticket = available_ticket_types(event, member).filter(pk=ticket_type_id).first()
    if not ticket:
        raise NotFound("Ticket type not found.")
    return ticket


@transaction.atomic
def create_ticket(event, *, actor, **values):
    from apps.events.services import _locked_event, _validate, _audit
    from apps.makerspaces.guards import require_module_locked

    event = _locked_event(event.pk)
    event.makerspace = require_module_locked(event.makerspace, "events")
    require_feature(event, "events.ticket_types")
    ticket = EventTicketType(event=event, makerspace=event.makerspace, **values)
    _validate(ticket)
    if ticket.sales_start_at and ticket.sales_end_at and ticket.sales_end_at <= ticket.sales_start_at:
        raise ValidationError("Sales end must be after sales start.")
    ticket.save()
    _audit(event, actor, "event.ticket_created", ticket)
    return ticket


def create_series_ticket_templates(series, templates, actor):
    from .services import _validate
    from apps.audit.services import record

    if not templates:
        return
    require_feature(series, "events.ticket_types")
    for values in templates:
        row = EventTicketType(series=series, makerspace=series.makerspace, **values)
        _validate(row)
        if row.sales_start_at and row.sales_end_at and row.sales_end_at <= row.sales_start_at:
            raise ValidationError("Sales end must be after sales start.")
        row.save()
        record(actor, "event.ticket_template_created", makerspace=series.makerspace, target=row)


def copy_series_tickets(series, event, *, actor):
    from .services import _audit

    fields = ("name", "amount", "audience", "capacity", "sales_start_at", "sales_end_at", "is_active")
    for template in series.ticket_types.all():
        ticket = EventTicketType.objects.create(
            makerspace=event.makerspace, event=event,
            **{field: getattr(template, field) for field in fields},
        )
        _audit(event, actor, "event.ticket_created", ticket)
